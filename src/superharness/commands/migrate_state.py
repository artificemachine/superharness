"""migrate-state — move legacy .superharness/state.sqlite3 to the XDG path.

Detects projects that were initialized before XDG state placement was
introduced (v1.60.0) and migrates their state.db to the correct location.

Stop the watcher and dashboard before migrating to avoid copying a partially
checkpointed WAL file:
    shux operator stop --project .
    shux migrate-state [--project DIR] [--dry-run] [--keep-legacy]
"""
from __future__ import annotations

import os
import shutil
import sys

import logging
logger = logging.getLogger(__name__)


def run_migrate_state(
    project_dir: str,
    dry_run: bool = False,
    keep_legacy: bool = False,
) -> int:
    """Migrate legacy state.sqlite3 to the XDG path.

    Returns 0 on success (or nothing to migrate), 1 on failure.
    """
    from superharness.utils.paths import resolve_xdg_state_db_path

    project_dir = os.path.abspath(project_dir)
    legacy_db = os.path.join(project_dir, ".superharness", "state.sqlite3")
    xdg_db = resolve_xdg_state_db_path(project_dir)

    print(f"Project:    {project_dir}")
    print(f"Legacy db:  {legacy_db}")
    print(f"XDG db:     {xdg_db}")
    print()

    legacy_exists = os.path.isfile(legacy_db)
    xdg_exists = os.path.isfile(xdg_db)

    if not legacy_exists:
        if xdg_exists:
            print("Already on XDG path — nothing to migrate.")
        else:
            print("No state.db found at either path — run 'shux init' first.")
        return 0

    if xdg_exists:
        # Split-brain: both paths exist. Report the conflict and suggest resolution.
        print("WARN split-brain detected: both XDG and legacy state DBs exist.")
        print(f"  XDG (active):  {xdg_db}")
        print(f"  Legacy:        {legacy_db}")
        print()
        print("The XDG db is the active source of truth. The legacy db is stale.")
        if dry_run:
            print("[dry-run] Would remove legacy db (no data loss — XDG is active).")
            print("Dry run complete — no changes made.")
            return 0
        if not keep_legacy:
            try:
                os.remove(legacy_db)
                print(f"Removed legacy db: {legacy_db}")
            except OSError as e:
                print(f"ERROR: could not remove legacy db: {e}", file=sys.stderr)
                return 1
        else:
            print("Keeping legacy db (--keep-legacy). Remove it manually when ready.")
        return 0

    xdg_dir = os.path.dirname(xdg_db)
    if dry_run:
        print(f"[dry-run] Would create directory: {xdg_dir}")
        print(f"[dry-run] Would copy: {legacy_db} → {xdg_db}")
        if not keep_legacy:
            print(f"[dry-run] Would remove: {legacy_db}")
        print("\nDry run complete — no changes made.")
        return 0

    try:
        os.makedirs(xdg_dir, exist_ok=True)
        shutil.copy2(legacy_db, xdg_db)
        print(f"Copied state.db → {xdg_db}")

        # Verify copy succeeded by checking file size matches
        src_size = os.path.getsize(legacy_db)
        dst_size = os.path.getsize(xdg_db)
        if src_size != dst_size:
            print(f"ERROR: size mismatch after copy ({src_size} vs {dst_size}). Aborting.", file=sys.stderr)
            os.remove(xdg_db)
            return 1

        # Also copy WAL/SHM if they exist (unlikely mid-use but safe)
        for ext in ("-shm", "-wal"):
            src_extra = legacy_db + ext
            if os.path.isfile(src_extra):
                shutil.copy2(src_extra, xdg_db + ext)

        if not keep_legacy:
            os.remove(legacy_db)
            for ext in ("-shm", "-wal"):
                extra = legacy_db + ext
                if os.path.isfile(extra):
                    os.remove(extra)
            print("Removed legacy state.db.")

        print()
        print("Migration complete. Run 'shux doctor' to verify.")
        return 0

    except Exception as exc:
        print(f"ERROR: migration failed: {exc}", file=sys.stderr)
        if os.path.isfile(xdg_db):
            try:
                os.remove(xdg_db)
            except Exception as e:
                logger.warning("migrate_state.py unexpected error: %s", e, exc_info=True)
                pass
        return 1


def cmd_migrate_state(args: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(
        prog="shux migrate-state",
        description="Move legacy .superharness/state.sqlite3 to the XDG state path.",
    )
    parser.add_argument("--project", default=".", help="Project directory (default: cwd)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    parser.add_argument("--keep-legacy", action="store_true", help="Keep the legacy file after copying")
    parsed = parser.parse_args(args)
    sys.exit(run_migrate_state(parsed.project, dry_run=parsed.dry_run, keep_legacy=parsed.keep_legacy))
