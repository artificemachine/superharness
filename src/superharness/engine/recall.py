"""Python port of engine/recall.rb.

Search .superharness/handoffs/ and ledger.md by keyword.

Usage:
    python3 -m superharness.engine.recall --project DIR "term" ["term2" ...]
    python3 -m superharness.engine.recall --project . --since 7d "deploy"

Multi-keyword logic: OR — any term matching in a file produces a result.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import logging
logger = logging.getLogger(__name__)

from superharness.engine.errors import OperationError, SuperharnessError, UsageError, handle_cli_error


def _try_date(val: object) -> date | None:
    if val is None:
        return None
    try:
        if isinstance(val, date):
            return val
        return date.fromisoformat(str(val)[:10])
    except (ValueError, TypeError):
        return None


def _file_date(path: Path, data: object) -> date | None:
    if isinstance(data, dict):
        for k in ("date", "created", "completed_at"):
            d = _try_date(data.get(k))
            if d:
                return d
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", path.name)
    if m:
        return _try_date(m.group(1))
    return None


DEFAULT_MAX_FRESH_DAYS = 14


def _resolve_max_fresh_days(cli_value: int | None) -> int:
    """Resolve the staleness threshold: explicit CLI value > env > default."""
    if cli_value is not None:
        return cli_value
    env = os.environ.get("SHUX_RECALL_FRESH_DAYS")
    if env:
        try:
            return int(env)
        except ValueError:
            logger.warning("Ignoring non-integer SHUX_RECALL_FRESH_DAYS=%r", env)
    return DEFAULT_MAX_FRESH_DAYS


def _age_days(d: date | None) -> int | None:
    """Whole days between `d` and today, or None when undated. Never negative."""
    if d is None:
        return None
    return max(0, (date.today() - d).days)


def _freshness_caveat(age_days: int | None, max_fresh_days: int) -> str:
    """Staleness caveat for a hit older than the threshold.

    Returns '' for undated or fresh (age <= threshold) hits — a caveat there
    is noise. Memories are point-in-time observations, not live state; an
    authoritative-looking file:line citation makes a stale claim sound more
    credible, not less, so old hits get an explicit verify-first warning.
    """
    if age_days is None or age_days <= max_fresh_days:
        return ""
    return (
        f"    ⚠ This hit is {age_days} days old — a point-in-time "
        f"observation, not live state. Verify file:line citations against "
        f"current code before asserting as fact."
    )


def _file_meta(path: Path, data: object) -> tuple[str, str]:
    agent = "unknown"
    task_id = path.stem.lstrip("0123456789-")
    if isinstance(data, dict):
        agent = str(data.get("agent") or data.get("completed_by") or data.get("owner") or "unknown")
        task_id = str(data.get("task_id") or data.get("task") or data.get("id") or task_id)
    return agent, task_id


def _ctx(lines: list[str], idx: int) -> str:
    start = max(idx - 1, 0)
    end = min(idx + 1, len(lines) - 1)
    snippets = [l.strip() for l in lines[start:end + 1] if l.strip()]
    return " / ".join(snippets[:3])


def search(project_dir: Path, terms: list[str], since_days: int | None = None) -> list[dict]:
    since_date = date.today() - timedelta(days=since_days) if since_days is not None else None
    sh_dir = project_dir / ".superharness"

    results: list[dict] = []

    # --- Scan handoffs from SQLite ---
    try:
        from superharness.engine import state_reader as _sr_h
        handoff_rows = _sr_h.get_handoffs(str(project_dir))
    except Exception as e:
        logger.warning("recall.py handoffs SQLite scan failed: %s", e, exc_info=True)
        handoff_rows = []
    for row in handoff_rows:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("content") or row.get("metadata") or row)
        fdate = _try_date(str(row.get("created_at", ""))[:10])
        if since_date and fdate and fdate < since_date:
            continue
        agent = str(row.get("from_agent") or row.get("agent") or "unknown")
        task_id = str(row.get("task_id") or "unknown")
        lines = raw.splitlines()
        snippets: list[str] = []
        count = 0
        for term in terms:
            for i, line in enumerate(lines):
                if term in line.lower():
                    count += 1
                    s = _ctx(lines, i)
                    if s and s not in snippets:
                        snippets.append(s)
        if count == 0:
            continue
        results.append({
            "date": fdate,
            "agent": agent,
            "task_id": task_id,
            "count": count,
            "snippets": snippets[:3],
        })

    # --- Scan tasks from SQLite (titles + subtasks) ---
    try:
        from superharness.engine import state_reader as _sr
        tasks = _sr.get_tasks(str(project_dir))
    except Exception as e:
        logger.warning("recall.py unexpected error: %s", e, exc_info=True)
        tasks = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        parent_status = str(t.get("status") or "")
        _scan = [(t, None)]
        for s in (t.get("subtasks") or []):
            if isinstance(s, dict):
                _scan.append((s, t))
        for entry, parent in _scan:
            title = str(entry.get("title") or "").lower()
            tid = str(entry.get("id") or "")
            hay = f"{tid} {title}".lower()
            count = sum(1 for term in terms if term in hay)
            if count == 0:
                continue
            label_kind = "subtask" if parent is not None else "task"
            snippet = f"[{label_kind}] {entry.get('title', '')}"
            if parent is not None:
                snippet += f" (parent: {parent.get('id', '')}, status: {parent_status})"
            results.append({
                "date": None,
                "agent": str(entry.get("owner") or "unknown"),
                "task_id": tid,
                "count": count,
                "snippets": [snippet[:160]],
            })

    # --- Scan ledger from SQLite ---
    try:
        from superharness.engine import state_reader as _sr_l
        ledger_entries = _sr_l.get_ledger_entries(str(project_dir), limit=500)
    except Exception as e:
        logger.warning("recall.py ledger SQLite scan failed: %s", e, exc_info=True)
        ledger_entries = []
    for entry in ledger_entries:
        if not isinstance(entry, dict):
            continue
        line = f"{entry.get('created_at', '')} {entry.get('agent', '')} {entry.get('action', '')}"
        ldate = _try_date(str(entry.get("created_at", ""))[:10])
        if since_date and ldate and ldate < since_date:
            continue
        agent = str(entry.get("agent") or "unknown")
        count = sum(1 for t in terms if t in line.lower())
        if count == 0:
            continue
        results.append({
            "date": ldate,
            "agent": agent,
            "task_id": "ledger",
            "count": count,
            "snippets": [line.strip()[:120]],
        })

    # Sort: newest first, then by match count descending
    results.sort(key=lambda r: (
        -(r["date"].toordinal() if r["date"] else 0),
        -r["count"],
    ))
    return results


def format_results(results: list[dict], max_fresh_days: int = DEFAULT_MAX_FRESH_DAYS) -> str:
    """Render search results as text, appending a staleness caveat to old hits."""
    blocks: list[str] = []
    for r in results:
        d = r.get("date")
        date_str = d.strftime("%Y-%m-%d") if d else "unknown"
        lines = [f"{date_str}  {r['agent']}  {r['task_id']}"]
        for s in r["snippets"]:
            lines.append(f'  "{s}"')
        caveat = _freshness_caveat(_age_days(d), max_fresh_days)
        if caveat:
            lines.append(caveat)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    p = argparse.ArgumentParser(
        prog="recall",
        description="Search .superharness/handoffs/ and ledger.md by keyword.",
    )
    p.add_argument("-p", "--project", default=os.getcwd(), help="Project directory (default: cwd)")
    p.add_argument("--since", metavar="Nd", default=None, help="Limit to last N days (e.g. 7d)")
    p.add_argument("--max-fresh-days", type=int, default=None,
                   help="Hits older than this many days get a staleness caveat "
                        "(default 14, or $SHUX_RECALL_FRESH_DAYS)")
    p.add_argument("terms", nargs="*", help="Search terms (OR logic)")
    opts = p.parse_args(argv)

    terms = [t.lower() for t in opts.terms]
    if not terms:
        raise UsageError("Error: at least one search term required", exit_code=1)

    project_dir = Path(opts.project).resolve()
    sh_dir = project_dir / ".superharness"
    if not sh_dir.is_dir():
        raise OperationError(
            f"Not a superharness project (no .superharness/): {project_dir}", exit_code=1
        )

    since_days: int | None = None
    if opts.since:
        m = re.fullmatch(r"(\d+)d", opts.since)
        if not m:
            raise UsageError(
                f"Invalid --since format (expected Nd, e.g. 7d): {opts.since}", exit_code=1
            )
        since_days = int(m.group(1))

    results = search(project_dir, terms, since_days)

    if not results:
        quoted = ", ".join(f'"{t}"' for t in terms)
        print(f"(no results for: {quoted})")
        return

    max_fresh_days = _resolve_max_fresh_days(opts.max_fresh_days)
    print(format_results(results, max_fresh_days))


if __name__ == "__main__":
    try:
        main()
    except SuperharnessError as e:
        handle_cli_error(e)
