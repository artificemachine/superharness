"""shux benchmark — display dispatch cost/duration leaderboard.

Usage:
  shux benchmark [--project DIR] [--top N] [--agents]
"""
from __future__ import annotations

import os
import sys


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
    opts = parser.parse_args(argv)

    project_dir = os.path.realpath(opts.project or os.getcwd())

    from superharness.engine.benchmark import leaderboard, format_leaderboard
    board = leaderboard(project_dir, top_n=opts.top)
    print(format_leaderboard(board, show_agents=opts.agents))


if __name__ == "__main__":
    main()
