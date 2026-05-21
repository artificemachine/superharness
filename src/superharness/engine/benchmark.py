"""Benchmark leaderboard — track dispatch cost, duration, and outcome per task.

Records are appended to .superharness/benchmark.jsonl (one JSON object per line).
The `leaderboard()` function aggregates records and returns a ranked summary.

Integration points:
- inbox_dispatch.py: record after each dispatch completes (done/failed)
- parallel_dispatch.py: record per-slot results via record_slot_result()
- `shux benchmark` command: display the leaderboard (see commands/benchmark.py)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import logging
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkRecord:
    task_id: str
    agent: str
    outcome: str          # done | failed | timeout | paused
    duration_seconds: float
    cost_usd: float
    model: str = ""
    slot_index: int = -1  # -1 = single dispatch; >= 0 = parallel slot
    fanout_n: int = 1     # number of parallel slots in the dispatch
    timestamp: str = ""   # ISO UTC


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _benchmark_path(project_dir: str) -> Path:
    return Path(project_dir) / ".superharness" / "benchmark.jsonl"


def record_dispatch(
    project_dir: str,
    task_id: str,
    agent: str,
    outcome: str,
    duration_seconds: float,
    cost_usd: float = 0.0,
    model: str = "",
    slot_index: int = -1,
    fanout_n: int = 1,
) -> None:
    """Append one benchmark record to benchmark.jsonl."""
    rec = BenchmarkRecord(
        task_id=task_id,
        agent=agent,
        outcome=outcome,
        duration_seconds=round(duration_seconds, 2),
        cost_usd=round(cost_usd, 6),
        model=model,
        slot_index=slot_index,
        fanout_n=fanout_n,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    path = _benchmark_path(project_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Build the full line before opening to minimize the write window
        line = json.dumps(asdict(rec)) + "\n"
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except Exception as e:
        logger.warning("benchmark.py unexpected error: %s", e, exc_info=True)
        pass
def load_records(project_dir: str) -> list[dict]:
    """Load all benchmark records from benchmark.jsonl."""
    path = _benchmark_path(project_dir)
    if not path.exists():
        return []
    records = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        logger.warning("benchmark.py unexpected error: %s", e, exc_info=True)
        pass
    return records


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

@dataclass
class TaskStats:
    task_id: str
    total_runs: int = 0
    successes: int = 0
    failures: int = 0
    avg_duration_seconds: float = 0.0
    total_cost_usd: float = 0.0
    avg_cost_usd: float = 0.0
    last_outcome: str = ""
    last_timestamp: str = ""
    success_rate: float = 0.0
    agents_used: list[str] = field(default_factory=list)


def aggregate(records: list[dict]) -> list[TaskStats]:
    """Aggregate raw records into per-task stats, sorted by total_cost desc."""
    from collections import defaultdict

    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        tid = r.get("task_id", "unknown")
        buckets[tid].append(r)

    stats: list[TaskStats] = []
    for task_id, recs in buckets.items():
        # Sort by timestamp ascending to get chronological order
        recs_sorted = sorted(recs, key=lambda x: x.get("timestamp", ""))
        successes = sum(1 for r in recs_sorted if r.get("outcome") == "done")
        failures = sum(1 for r in recs_sorted if r.get("outcome") in ("failed", "timeout"))
        total_duration = sum(r.get("duration_seconds", 0.0) for r in recs_sorted)
        total_cost = sum(r.get("cost_usd", 0.0) for r in recs_sorted)
        n = len(recs_sorted)
        agents = list(dict.fromkeys(r.get("agent", "") for r in recs_sorted))  # ordered unique

        ts = TaskStats(
            task_id=task_id,
            total_runs=n,
            successes=successes,
            failures=failures,
            avg_duration_seconds=round(total_duration / n, 2) if n else 0.0,
            total_cost_usd=round(total_cost, 6),
            avg_cost_usd=round(total_cost / n, 6) if n else 0.0,
            last_outcome=recs_sorted[-1].get("outcome", "") if recs_sorted else "",
            last_timestamp=recs_sorted[-1].get("timestamp", "") if recs_sorted else "",
            success_rate=round(successes / n, 2) if n else 0.0,
            agents_used=agents,
        )
        stats.append(ts)

    # Sort by total_cost descending (most expensive tasks first)
    stats.sort(key=lambda s: -s.total_cost_usd)
    return stats


def leaderboard(project_dir: str, top_n: int = 20) -> list[TaskStats]:
    """Return the top_n most expensive/active tasks as TaskStats."""
    records = load_records(project_dir)
    return aggregate(records)[:top_n]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_leaderboard(stats: list[TaskStats], show_agents: bool = False) -> str:
    """Return a human-readable leaderboard table."""
    if not stats:
        return "No benchmark records found."

    _W = 78
    header = f"{'Task ID':<38} {'Runs':>4} {'OK':>3} {'Fail':>4} {'Avg(s)':>7} {'Total $':>9} {'Rate':>5}"
    lines = [header, "-" * _W]
    for s in stats:
        rate_pct = f"{s.success_rate * 100:.0f}%"
        dur = f"{s.avg_duration_seconds:.1f}"
        cost = f"${s.total_cost_usd:.4f}"
        # Truncate long task IDs to keep table aligned
        tid = s.task_id if len(s.task_id) <= 38 else s.task_id[:36] + ".."
        line = f"{tid:<38} {s.total_runs:>4} {s.successes:>3} {s.failures:>4} {dur:>7} {cost:>9} {rate_pct:>5}"
        if show_agents:
            line += f"  [{', '.join(s.agents_used)}]"
        lines.append(line)

    total_cost = sum(s.total_cost_usd for s in stats)
    lines.append("-" * _W)
    lines.append(f"Total cost tracked: ${total_cost:.4f} across {len(stats)} tasks")
    return "\n".join(lines)
