"""shux backup state / shux restore state — SQLite online backup and restore.

Uses sqlite3.backup() which is safe during live writes (WAL mode).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone


def _now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _db_path(project_dir: str) -> str:
    return os.path.join(project_dir, ".superharness", "state.sqlite3")


def backup(project_dir: str, out_path: str | None = None) -> int:
    """Create a safe online backup of state.sqlite3.

    Safe during live writes — uses sqlite3.backup() which operates at the
    page level and respects WAL mode.

    Returns 0 on success, 1 on failure.
    """
    src = _db_path(project_dir)
    if not os.path.exists(src):
        print(f"backup: no state.sqlite3 found at {src}", file=sys.stderr)
        return 1

    backup_dir = os.path.expanduser("~/.superharness-backups")
    os.makedirs(backup_dir, exist_ok=True)

    if out_path is None:
        tag = _now_tag()
        proj_name = os.path.basename(os.path.abspath(project_dir))
        out_path = os.path.join(backup_dir, f"state-{proj_name}-{tag}.sqlite3")

    try:
        src_conn = sqlite3.connect(src, timeout=10)
        dst_conn = sqlite3.connect(out_path)
        try:
            src_conn.backup(dst_conn, pages=50)
            dst_conn.commit()
        finally:
            dst_conn.close()
            src_conn.close()
    except sqlite3.Error as exc:
        print(f"backup: failed: {exc}", file=sys.stderr)
        return 1

    size_kb = os.path.getsize(out_path) // 1024
    print(f"backup: written to {out_path} ({size_kb} KB)")
    return 0


def restore(project_dir: str, from_path: str) -> int:
    """Restore state.sqlite3 from a backup file.

    Stops short if the source backup is not a valid SQLite file.
    Creates a timestamped .bak of the current DB before replacing.

    Returns 0 on success, 1 on failure.
    """
    if not os.path.exists(from_path):
        print(f"restore: source not found: {from_path}", file=sys.stderr)
        return 1

    # Validate source is a real SQLite file
    try:
        test_conn = sqlite3.connect(from_path)
        test_conn.execute("SELECT count(*) FROM sqlite_master")
        test_conn.close()
    except sqlite3.Error as exc:
        print(f"restore: source is not a valid SQLite file: {exc}", file=sys.stderr)
        return 1

    dst = _db_path(project_dir)

    # Back up current DB before replacing
    if os.path.exists(dst):
        bak = dst + f".bak-{_now_tag()}"
        try:
            shutil.copy2(dst, bak)
            print(f"restore: saved current DB to {bak}")
        except OSError as exc:
            print(f"restore: could not back up current DB: {exc}", file=sys.stderr)
            return 1

    # Copy source to destination
    try:
        src_conn = sqlite3.connect(from_path, timeout=10)
        dst_conn = sqlite3.connect(dst)
        try:
            src_conn.backup(dst_conn, pages=50)
            dst_conn.commit()
        finally:
            dst_conn.close()
            src_conn.close()
    except sqlite3.Error as exc:
        print(f"restore: failed: {exc}", file=sys.stderr)
        return 1

    print(f"restore: restored {from_path} → {dst}")
    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="backup-state",
        description="Backup or restore the superharness SQLite state database",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    bk = sub.add_parser("backup", help="Create a safe online backup of state.sqlite3")
    bk.add_argument("--project", "-p", default=".", help="Project directory")
    bk.add_argument("--out", help="Output path (default: ~/.superharness-backups/state-<proj>-<ts>.sqlite3)")

    rs = sub.add_parser("restore", help="Restore state.sqlite3 from a backup file")
    rs.add_argument("--project", "-p", default=".", help="Project directory")
    rs.add_argument("--from", dest="from_path", required=True, help="Backup file to restore from")

    args = parser.parse_args(argv)
    project_dir = os.path.abspath(args.project)

    if args.action == "backup":
        sys.exit(backup(project_dir, out_path=args.out))
    elif args.action == "restore":
        sys.exit(restore(project_dir, from_path=args.from_path))


if __name__ == "__main__":
    main()
