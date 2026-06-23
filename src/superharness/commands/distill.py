"""shux distill — distill recent handoffs+ledger into curated project lessons.

Iteration 2: read-only. `--dry-run` (the default) prints candidate lessons
extracted from the session record without writing anything. The `--apply`
write path lands in Iteration 3.

Usage:
  shux distill [--project DIR] [--since Nd] [--max-lessons N] [--dry-run | --apply]
"""
from __future__ import annotations

import os
import re
import sys

from superharness.engine import distiller


def default_llm_fn(system: str, user: str) -> str | None:
    """Production LLM call: Anthropic cheap tier via summarizer_providers.complete."""
    from superharness.engine import summarizer_providers
    return summarizer_providers.complete(system, user)


def _parse_since(value: str | None) -> int | None:
    if not value:
        return None
    m = re.fullmatch(r"(\d+)d", value)
    if not m:
        print(f"Invalid --since format (expected Nd, e.g. 7d): {value}", file=sys.stderr)
        sys.exit(1)
    return int(m.group(1))


def main(argv: list[str] | None = None) -> int:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    p = argparse.ArgumentParser(
        prog="distill",
        description="Distill recent handoffs+ledger into curated project lessons.",
    )
    p.add_argument("-p", "--project", default=os.getcwd(), help="Project directory (default: cwd)")
    p.add_argument("--since", metavar="Nd", default=None, help="Only consider the last N days (e.g. 30d)")
    p.add_argument("--max-lessons", type=int, default=distiller.MAX_LESSONS_DEFAULT,
                   help=f"Max lessons per run (default {distiller.MAX_LESSONS_DEFAULT})")
    p.add_argument("--schedule", nargs="?", const="0 3 * * *", default=None, metavar="CRON",
                   help="Register a nightly distill job (default cron '0 3 * * *') and exit")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Print candidates, write nothing (default)")
    mode.add_argument("--apply", action="store_true", help="Persist lessons to project pitfalls.md")
    opts = p.parse_args(argv)

    if opts.schedule is not None:
        from superharness.commands import schedule
        return schedule.add_distill_schedule(opts.project, opts.schedule)

    since_days = _parse_since(opts.since)
    transcript = distiller.gather_candidates(opts.project, since_days)
    lessons = distiller.distill(transcript, llm_fn=default_llm_fn, max_lessons=opts.max_lessons)

    if not lessons:
        print("(no lessons distilled)")
        return 0

    for e in lessons:
        print(f"[{e.type} c={e.confidence:.2f}] {e.text}")

    if opts.apply:
        from superharness.engine import agent_memory
        n = agent_memory.apply_lessons(lessons, opts.project)
        skipped = len(lessons) - n
        print(f"\nApplied {n} lesson(s) to pitfalls.md ({skipped} skipped by dedup/confidence).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
