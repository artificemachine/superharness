"""SQLite-only mode — permanent.

The YAML→SQLite migration is complete. All state lives in SQLite.
YAML files are no longer read or written for operational purposes.
Use `shux export-yaml` to generate human-readable YAML snapshots.
"""
from __future__ import annotations


def is_sqlite_only() -> bool:
    """Always True — SQLite is the sole source of truth."""
    return True
