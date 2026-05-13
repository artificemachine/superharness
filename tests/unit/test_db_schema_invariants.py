"""Regression guards for db.py schema integrity.

Prevents the class of bugs where:
- A migration function is added to _MIGRATIONS but CURRENT_SCHEMA_VERSION is not bumped
- CURRENT_SCHEMA_VERSION is bumped but no migration function is added
- A new table is added to a DAO but never wired into init_db migrations
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from superharness.engine.db import (
    CURRENT_SCHEMA_VERSION,
    _MIGRATIONS,
    get_connection,
    init_db,
)


def test_migration_count_matches_schema_version():
    """CURRENT_SCHEMA_VERSION must equal len(_MIGRATIONS).

    If you add a migration function but forget to bump the version (or vice
    versa), this test fails immediately rather than silently skipping the new
    migration on all fresh databases.
    """
    assert len(_MIGRATIONS) == CURRENT_SCHEMA_VERSION, (
        f"_MIGRATIONS has {len(_MIGRATIONS)} entries but "
        f"CURRENT_SCHEMA_VERSION={CURRENT_SCHEMA_VERSION}. "
        "Bump CURRENT_SCHEMA_VERSION or add the missing migration function."
    )


def test_init_db_creates_all_known_tables(tmp_path):
    """init_db on a fresh directory must create every table used by DAOs."""
    (tmp_path / ".superharness").mkdir()
    conn = get_connection(str(tmp_path))
    init_db(conn)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    required = {
        "schema_migrations",
        "tasks",
        "inbox",
        "handoffs",
        "failures",
        "decisions",
        "ledger",
        "discussions",
        "discussion_rounds",
        "task_observations",
        "summarizer_calls",
        "operator_commands",
    }
    missing = required - tables
    assert not missing, f"Tables missing after init_db: {missing}"


def test_schema_version_advances_on_fresh_db(tmp_path):
    """PRAGMA user_version must equal CURRENT_SCHEMA_VERSION after init_db."""
    (tmp_path / ".superharness").mkdir()
    conn = get_connection(str(tmp_path))
    init_db(conn)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert version == CURRENT_SCHEMA_VERSION
