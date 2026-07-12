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
import sqlite3
import sys

import logging
logger = logging.getLogger(__name__)


def _table_columns(db_path: str, table: str) -> set[str]:
    """Return the column names of `table` in the sqlite db at `db_path`.

    Empty set if the file doesn't exist, the table doesn't exist, or the
    file can't be opened as sqlite — callers treat that as "nothing to
    compare" rather than a hard error.
    """
    if not os.path.isfile(db_path):
        return set()
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            return {r[1] for r in rows}
        finally:
            conn.close()
    except sqlite3.Error:
        return set()


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
        # Split-brain: both paths exist. get_connection() always prefers the
        # XDG path, so it's the one actually in use — but "in use" doesn't
        # mean "more complete". A DB can claim every migration applied
        # (schema_migrations + PRAGMA user_version) while missing columns a
        # migration was supposed to add, if it was last migrated through a
        # historical window where that drift could happen silently (see
        # db._heal_known_migration_drift). Deleting the "stale" copy without
        # checking would silently make that corruption permanent. Compare
        # schemas before assuming which one to keep.
        print("WARN split-brain detected: both XDG and legacy state DBs exist.")
        print(f"  XDG (active):  {xdg_db}")
        print(f"  Legacy:        {legacy_db}")
        print()

        xdg_cols = _table_columns(xdg_db, "agent_heartbeats")
        legacy_cols = _table_columns(legacy_db, "agent_heartbeats")
        xdg_behind = bool(legacy_cols - xdg_cols)

        if xdg_behind:
            print("WARN XDG db's agent_heartbeats is missing columns the legacy db has:")
            print(f"  Missing: {sorted(legacy_cols - xdg_cols)}")
            print("Refusing to auto-resolve — the 'active' copy is schema-behind the 'stale' one.")
            print("Manual resolution required. Options:")
            print(f"  - Keep legacy, discard XDG: rm {xdg_db} && shux migrate-state --project {project_dir}")
            print(f"  - Inspect both and merge manually before removing either.")
            return 1

        print("The XDG db is the active source of truth and is not schema-behind the legacy db.")
        if dry_run:
            print("[dry-run] Would remove legacy db (no data loss — XDG is active and not behind).")
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
