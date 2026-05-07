"""SQLite-only mode — permanent.

The YAML→SQLite migration is complete. All state lives in SQLite.
YAML files are no longer read or written for operational purposes.
Use `shux export-yaml` to generate human-readable YAML snapshots.
"""
from __future__ import annotations


def is_sqlite_only(project_dir: str | None = None) -> bool:
    """Return True if strict SQLite-only mode is active (no YAML writes).

    Checks STATE_BACKEND env var first for explicit overrides, then falls back
    to detecting whether a SQLite DB already exists in the project — the
    presence of the DB is the canonical signal that migration is complete.
    """
    import os
    backend = os.environ.get("STATE_BACKEND", "").strip().lower()
    if backend == "sqlite_only":
        return True
    if backend == "dual":
        return False
    if project_dir is not None:
        db_path = os.path.join(project_dir, ".superharness", "state.sqlite3")
        return os.path.isfile(db_path)
    # Migration is permanent — default to sqlite_only when no explicit override.
    return True
