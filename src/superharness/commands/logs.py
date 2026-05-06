"""shux logs — view the centralized superharness log."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _log_path(audit: bool) -> Path:
    from superharness.logging_utils import _resolve_log_file
    if audit:
        return _resolve_log_file("SUPERHARNESS_AUDIT_LOG_FILE", "superharness-audit.log")
    return _resolve_log_file("SUPERHARNESS_LOG_FILE", "superharness.log")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="logs", description="Show or tail the superharness log file."
    )
    p.add_argument("--audit", action="store_true",
                   help="Show the audit log instead of the main log")
    p.add_argument("--tail", "-f", action="store_true",
                   help="Follow log output (like tail -f)")
    p.add_argument("--lines", "-n", type=int, default=200,
                   help="How many trailing lines to print (default 200)")
    p.add_argument("--level", default=None,
                   choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                   help="Filter by minimum level")
    p.add_argument("--path", action="store_true",
                   help="Print the log file path and exit")
    p.add_argument("--clear", action="store_true",
                   help="Truncate the log file (irreversible)")
    opts = p.parse_args(argv)

    log_file = _log_path(opts.audit)
    if opts.path:
        print(log_file)
        return 0
    if not log_file.is_file():
        print(f"No log file yet at: {log_file}", file=sys.stderr)
        return 1
    if opts.clear:
        log_file.write_text("")
        print(f"Cleared {log_file}")
        return 0

    level_rank = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
    min_rank = level_rank.get(opts.level, -1) if opts.level else -1

    def _line_passes(line: str) -> bool:
        if min_rank < 0:
            return True
        for level, rank in level_rank.items():
            if f" {level} " in line:
                return rank >= min_rank
        return True

    if opts.tail:
        # Stream new lines.
        import time
        with log_file.open("r", encoding="utf-8") as f:
            f.seek(0, os.SEEK_END)
            try:
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.5)
                        continue
                    if _line_passes(line):
                        sys.stdout.write(line)
                        sys.stdout.flush()
            except KeyboardInterrupt:
                return 0

    # One-shot: print the trailing N lines.
    with log_file.open("r", encoding="utf-8") as f:
        all_lines = f.readlines()
    tail = [ln for ln in all_lines if _line_passes(ln)][-opts.lines:]
    sys.stdout.writelines(tail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
