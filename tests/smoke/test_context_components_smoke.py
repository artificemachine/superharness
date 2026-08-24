"""Smoke test for the context_component / dispatch_context tables (schema v39).

See docs/PLAN-typed-boundaries-context-hashing.md, Iteration 3.
"""

from __future__ import annotations

from superharness.engine.db import CURRENT_SCHEMA_VERSION, get_connection, init_db


def test_migration_v39_creates_tables(tmp_path):
    conn = get_connection(str(tmp_path))
    try:
        init_db(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "context_component" in tables
        assert "dispatch_context" in tables

        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 39
        assert CURRENT_SCHEMA_VERSION == 39
    finally:
        conn.close()
