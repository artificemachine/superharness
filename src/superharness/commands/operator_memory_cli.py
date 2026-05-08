"""shux operator-memory — inspect and manage operator pattern memory.

Usage:
    shux operator-memory [--project PATH]        # list all remembered patterns
    shux operator-forget SIG [--project PATH]    # remove a pattern from memory
"""
from __future__ import annotations

import os
import sys


def _db_path(project_dir: str) -> str:
    return os.path.join(project_dir, ".superharness", "state.sqlite3")


# ---------------------------------------------------------------------------
# operator-memory: list
# ---------------------------------------------------------------------------

def cmd_operator_memory(args: list[str] | None = None) -> None:
    """List all operator memory patterns with confidence scores."""
    if args is None:
        args = sys.argv[1:]

    import argparse

    parser = argparse.ArgumentParser(
        prog="shux operator-memory",
        description="List remembered failure patterns and their confidence.",
    )
    parser.add_argument("--project", "-p", default=os.getcwd(),
                        help="Project directory (default: cwd)")

    opts = parser.parse_args(args)
    project_dir = os.path.realpath(opts.project)
    db_path = _db_path(project_dir)

    if not os.path.isfile(db_path):
        print("operator-memory: no state database found")
        print(f"  expected: {db_path}")
        print("  tip: run 'shux watch' to start the watcher and populate memory")
        sys.exit(0)

    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(db_path)
    om.ensure_table()

    patterns = om.list_all()
    if not patterns:
        print("operator-memory: no remembered patterns (yet)")
        print("  Patterns are seeded when failures match known signatures.")
        print("  Run 'shux watch' with active tasks to build memory.")
        return

    print(f"operator-memory ({len(patterns)} pattern(s))")
    print()
    print(f"{'SIGNATURE':<30} {'CONF':>6} {'HITS':>5} {'MISS':>5} {'RESOLUTION'}")
    print("-" * 90)

    for p in patterns:
        sig = p["pattern_signature"][:28]
        conf = p["confidence"]
        hits = p["hit_count"]
        misses = p["miss_count"]
        res = (p["resolution"] or "")[:40]
        print(f"{sig:<30} {conf:6.2f} {hits:5} {misses:5} {res}")

    print()
    print("  forget a pattern:  shux operator-forget <signature>")


# ---------------------------------------------------------------------------
# operator-forget: remove
# ---------------------------------------------------------------------------

def cmd_operator_forget(args: list[str] | None = None) -> None:
    """Remove a pattern from operator memory."""
    if args is None:
        args = sys.argv[1:]

    import argparse

    parser = argparse.ArgumentParser(
        prog="shux operator-forget",
        description="Remove a remembered failure pattern.",
    )
    parser.add_argument("signature", nargs="?", default=None,
                        help="Pattern signature to forget (e.g., 'import_error')")
    parser.add_argument("--project", "-p", default=os.getcwd(),
                        help="Project directory (default: cwd)")

    opts = parser.parse_args(args)
    project_dir = os.path.realpath(opts.project)
    db_path = _db_path(project_dir)

    if not opts.signature:
        print("usage: shux operator-forget <signature>")
        print("  List known signatures: shux operator-memory")
        sys.exit(1)

    if not os.path.isfile(db_path):
        print(f"operator-forget: no state database at {db_path}")
        sys.exit(1)

    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(db_path)
    om.ensure_table()

    before = om.find_pattern(opts.signature)
    if before is None:
        print(f"operator-forget: no pattern '{opts.signature}' found in memory")
        print("  list known patterns: shux operator-memory")
        sys.exit(1)

    om.forget(opts.signature)
    print(f"operator-forget: removed '{opts.signature}'")
    print(f"  resolution was: {before['resolution'][:120]}")
    print(f"  confidence was: {before['confidence']:.2f}")
