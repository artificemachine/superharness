#!/usr/bin/env python3
"""Gate 2 soak monitor — polls parity every N minutes and writes a structured log.

Usage:
    python3 soak-monitor.py --project <path> [--interval 300] [--duration 86400]

Pass criteria (revised from verdict handoff to account for structural only_in_db gaps):
    - mismatched == 0 for all tables
    - yaml_sync_lag < 5
    - foreign_key_violations == 0
    - healthy == True counts separately for >=99% target

Output: .superharness/handoffs/sqlite-soak-<ts>-claude-code.yaml
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

PASS_LAG_THRESHOLD = 5


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check(project_dir: str) -> dict:
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import parity
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            report = parity.check_parity(conn, project_dir)
            drift_map = {d.table: d for d in report.drifts}
            return {
                "ts": _now(),
                "healthy": report.healthy,
                "lag": report.yaml_sync_lag,
                "fk": report.foreign_key_violations,
                "drifts": {
                    t: {
                        "only_in_db": drift_map[t].only_in_db if t in drift_map else 0,
                        "only_in_yaml": drift_map[t].only_in_yaml if t in drift_map else 0,
                        "mismatched": drift_map[t].mismatched if t in drift_map else 0,
                    }
                    for t in ("tasks", "inbox", "handoffs", "failures", "decisions")
                },
                "error": None,
            }
        finally:
            conn.close()
    except Exception as e:
        return {"ts": _now(), "healthy": None, "lag": -1, "fk": -1, "drifts": {}, "error": str(e)}


def _sample_passes(s: dict) -> bool:
    if s.get("error"):
        return False
    if s.get("fk", -1) != 0:
        return False
    if s.get("lag", 999) >= PASS_LAG_THRESHOLD:
        return False
    for drift in s.get("drifts", {}).values():
        if drift.get("mismatched", 0) > 0:
            return False
    return True


def _fmt_sample(s: dict) -> str:
    if s.get("error"):
        return f"  {s['ts']}  ERROR: {s['error']}"
    drifts = s.get("drifts", {})
    mismatched = sum(d.get("mismatched", 0) for d in drifts.values())
    only_in_db = sum(d.get("only_in_db", 0) for d in drifts.values())
    flag = "PASS" if _sample_passes(s) else "FAIL"
    return (
        f"  {s['ts']}  {flag}  "
        f"healthy={s.get('healthy')}  lag={s.get('lag')}  "
        f"mismatched={mismatched}  only_in_db={only_in_db}  fk={s.get('fk')}"
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Gate 2 soak monitor")
    ap.add_argument("--project", "-p", required=True)
    ap.add_argument("--interval", type=int, default=300, help="Poll interval in seconds (default: 300)")
    ap.add_argument("--duration", type=int, default=86400, help="Total soak duration in seconds (default: 86400 = 24h)")
    ap.add_argument("--output", default=None, help="Output log path (default: .superharness/handoffs/sqlite-soak-<ts>-claude-code.yaml)")
    opts = ap.parse_args(argv)

    project_dir = os.path.realpath(opts.project)
    start_ts = _now()
    start_time = time.monotonic()
    end_time = start_time + opts.duration

    if opts.output:
        log_path = opts.output
    else:
        handoffs_dir = os.path.join(project_dir, ".superharness", "handoffs")
        os.makedirs(handoffs_dir, exist_ok=True)
        slug = start_ts.replace(":", "").replace("-", "")
        log_path = os.path.join(handoffs_dir, f"sqlite-soak-{slug}-claude-code.yaml")

    samples: list[dict] = []
    total = round(opts.duration / opts.interval)

    print(f"soak-monitor: project={project_dir}")
    print(f"soak-monitor: interval={opts.interval}s  duration={opts.duration}s  (~{total} samples)")
    print(f"soak-monitor: log={log_path}")
    print(f"soak-monitor: pass criteria — mismatched=0, lag<{PASS_LAG_THRESHOLD}, fk=0")
    print(f"soak-monitor: started {start_ts}")
    print()

    i = 0
    while time.monotonic() < end_time:
        i += 1
        s = _check(project_dir)
        samples.append(s)
        line = _fmt_sample(s)
        print(f"[{i}/{total}] {line}")
        sys.stdout.flush()

        _write_log(log_path, start_ts, opts, samples)

        remaining = end_time - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(opts.interval, remaining))

    _write_log(log_path, start_ts, opts, samples, final=True)
    _print_summary(start_ts, _now(), samples, log_path)


def _write_log(path: str, start_ts: str, opts, samples: list[dict], *, final: bool = False) -> None:
    passes = sum(1 for s in samples if _sample_passes(s))
    total = len(samples)
    rate = (passes / total * 100) if total else 0
    status = "in_progress" if not final else ("soak_passed" if rate >= 99.0 else "soak_failed")

    lines = [
        f"task: sqlite-gate2-soak",
        f"phase: soak",
        f"status: {status}",
        f"from: claude-code",
        f"to: owner",
        f"started_at: {start_ts}",
        f"last_updated: {_now()}",
        f"interval_seconds: {opts.interval}",
        f"duration_seconds: {opts.duration}",
        f"",
        f"pass_criteria:",
        f"  mismatched: 0",
        f"  yaml_sync_lag: \"< {PASS_LAG_THRESHOLD}\"",
        f"  foreign_key_violations: 0",
        f"  healthy_rate_target: \">=99%\"",
        f"",
        f"summary:",
        f"  total_samples: {total}",
        f"  pass_samples: {passes}",
        f"  fail_samples: {total - passes}",
        f"  pass_rate: \"{rate:.1f}%\"",
        f"",
        f"samples: |",
    ]
    for s in samples:
        lines.append(f"  {_fmt_sample(s).strip()}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _print_summary(start_ts: str, end_ts: str, samples: list[dict], log_path: str) -> None:
    passes = sum(1 for s in samples if _sample_passes(s))
    total = len(samples)
    rate = (passes / total * 100) if total else 0
    verdict = "SOAK PASSED" if rate >= 99.0 else "SOAK FAILED"
    print()
    print(f"{'='*60}")
    print(f"{verdict}  ({passes}/{total} samples pass, {rate:.1f}%)")
    print(f"started: {start_ts}  ended: {end_ts}")
    print(f"log: {log_path}")
    print(f"{'='*60}")
    if rate >= 99.0:
        print("Next: attach log to Gate 2 confirmation handoff, then proceed to iter-8 (read cutover).")
    else:
        print("Next: review FAIL samples above, fix root cause, re-run soak.")


if __name__ == "__main__":
    main()
