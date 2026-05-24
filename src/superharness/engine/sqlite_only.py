"""SQLite-only mode — permanent.

Migration complete as of 2026-05-24. All operational state reads are routed
through DAOs / state_reader. The ratchet guard BASELINE is empty.

YAML files are export-only artifacts; they are never read as authoritative input.
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
        from superharness.utils.paths import resolve_active_state_db_path
        db_path = resolve_active_state_db_path(project_dir)
        return os.path.isfile(db_path)
    # Migration is permanent — default to sqlite_only when no explicit override.
    return True
