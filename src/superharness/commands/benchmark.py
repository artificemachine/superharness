"""shux benchmark — display dispatch cost/duration leaderboard.

Usage:
  shux benchmark [--project DIR] [--top N] [--agents]
"""
from __future__ import annotations

import os
import sys

import logging
logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="benchmark",
        description="Show dispatch cost and duration leaderboard",
    )
    parser.add_argument("--project", "-p", default=None,
                        help="Project directory (default: current dir)")
    parser.add_argument("--top", "-n", type=int, default=20,
                        help="Number of tasks to show (default: 20)")
    parser.add_argument("--agents", action="store_true",
                        help="Show which agents were used per task")
    parser.add_argument("--models", action="store_true",
                        help="Show cost breakdown by model instead of by task")
    opts = parser.parse_args(argv)

    project_dir = os.path.realpath(opts.project or os.getcwd())

    if opts.models:
        from superharness.engine.benchmark import load_records
        from superharness.engine.model_budget import check_budget
        _print_model_breakdown(project_dir, load_records(project_dir))
        return

    from superharness.engine.benchmark import leaderboard, format_leaderboard
    board = leaderboard(project_dir, top_n=opts.top)
    print(format_leaderboard(board, show_agents=opts.agents))


def _print_model_breakdown(project_dir: str, records: list) -> None:
    """Print per-model cost/token/task breakdown for the last 7 days."""
    import datetime
    from collections import defaultdict

    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).isoformat()
    recent = [r for r in records if r.get("timestamp", "") >= cutoff]

    if not recent:
        print("No dispatch data in the last 7 days.")
        return

    buckets: dict[str, list] = defaultdict(list)
    for r in recent:
        model = r.get("model") or "unknown"
        buckets[model].append(r)

    rows = []
    for model, recs in buckets.items():
        tasks = len(recs)
        cost = sum(float(r.get("cost_usd", 0)) for r in recs)
        rows.append((model, tasks, cost))

    rows.sort(key=lambda x: -x[2])

    total_tasks = sum(r[1] for r in rows)
    total_cost = sum(r[2] for r in rows)

    header = f"{'Model':<30} {'Tasks':>6}  {'Cost':>8}"
    sep = "─" * len(header)
    print(f"Model Usage (last 7 days)\n{sep}")
    print(header)
    print(sep)
    for model, tasks, cost in rows:
        print(f"{model:<30} {tasks:>6}  ${cost:>7.2f}")
    print(sep)
    print(f"{'Total':<30} {total_tasks:>6}  ${total_cost:>7.2f}")

    # Show budget summary if configured
    try:
        from superharness.engine.model_budget import _load_budget_config
        cfg = _load_budget_config(project_dir)
        weekly = cfg.get("weekly_limit")
        if weekly:
            pct = total_cost / float(weekly) * 100
            print(f"Budget: ${weekly:.2f}/week — {pct:.0f}% used")
    except Exception as e:
        logger.warning("benchmark.py unexpected error: %s", e, exc_info=True)
        pass
if __name__ == "__main__":
    main()
