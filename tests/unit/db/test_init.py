from __future__ import annotations

import sqlite3
import os
from pathlib import Path

import pytest
from superharness.engine.state_errors import ConnectionError
from superharness.utils.paths import resolve_xdg_state_db_path

def test_db_file_created(monkeypatch, tmp_path: Path):
    from superharness.engine.db import get_connection
    state_dir = str(tmp_path / "xdg_state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)

    project = tmp_path / "project"
    project.mkdir()

    conn = get_connection(str(project))
    try:
        db_path = resolve_xdg_state_db_path(str(project))
        assert os.path.isfile(db_path)
    finally:
        conn.close()

def test_init_db_creates_tables(db_conn: sqlite3.Connection):
    cursor = db_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    
    expected_tables = {
        "schema_migrations",
        "tasks",
        "task_dependencies",
        "inbox",
        "handoffs",
        "failures",
        "decisions",
        "ledger",
        "review_store",
        "watcher_instance",
        "yaml_sync_queue"
    }
    for table in expected_tables:
        assert table in tables, f"Table {table} missing"

def test_pragma_values(db_conn: sqlite3.Connection):
    # WAL mode
    cursor = db_conn.execute("PRAGMA journal_mode")
    assert cursor.fetchone()[0].lower() == "wal"
    
    # FK enforcement
    cursor = db_conn.execute("PRAGMA foreign_keys")
    assert cursor.fetchone()[0] == 1
    
    # User version matches current schema
    from superharness.engine.db import CURRENT_SCHEMA_VERSION
    cursor = db_conn.execute("PRAGMA user_version")
    assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

def test_schema_migrations_row(db_conn: sqlite3.Connection):
    cursor = db_conn.execute("SELECT version FROM schema_migrations WHERE version=1")
    assert cursor.fetchone() is not None

def test_idempotency(db_conn: sqlite3.Connection):
    from superharness.engine.db import init_db, CURRENT_SCHEMA_VERSION
    # Should not raise even if called again
    init_db(db_conn)
    init_db(db_conn)

    cursor = db_conn.execute("SELECT count(*) FROM schema_migrations")
    assert cursor.fetchone()[0] == CURRENT_SCHEMA_VERSION

def test_sqlite_version_check(monkeypatch, tmp_path: Path):
    import sqlite3
    # Force a low version for testing
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 34, 0))

    from superharness.engine.db import get_connection
    project = tmp_path
    (project / ".superharness").mkdir()

    with pytest.raises(ConnectionError, match="SQLite version 3.35.0 or higher required"):
        get_connection(str(project))


# ---------------------------------------------------------------------------
# XDG path migration (Iteration 4 — get_connection uses XDG for new projects)
# ---------------------------------------------------------------------------

def test_get_connection_creates_at_xdg_for_new_project(monkeypatch, tmp_path):
    """A fresh project directory causes get_connection to create state.db at the XDG path."""
    from superharness.engine.db import get_connection
    state_dir = str(tmp_path / "xdg_state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)

    project = str(tmp_path / "newproject")
    os.makedirs(project)
    conn = get_connection(project)
    conn.close()

    expected = resolve_xdg_state_db_path(project)
    assert os.path.isfile(expected), f"Expected db at {expected}"


def test_get_connection_uses_legacy_when_only_legacy_exists(monkeypatch, tmp_path):
    """Existing projects with .superharness/state.sqlite3 continue to work unchanged."""
    from superharness.engine.db import get_connection, init_db
    state_dir = str(tmp_path / "xdg_state_empty")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)

    project = str(tmp_path / "oldproject")
    legacy_dir = os.path.join(project, ".superharness")
    os.makedirs(legacy_dir)
    legacy_db = os.path.join(legacy_dir, "state.sqlite3")
    conn0 = sqlite3.connect(legacy_db)
    conn0.row_factory = sqlite3.Row
    init_db(conn0)
    conn0.close()

    conn = get_connection(project)
    conn.close()
    xdg = resolve_xdg_state_db_path(project)
    assert not os.path.isfile(xdg), "XDG db must not be created when legacy exists"


def test_get_connection_prefers_xdg_when_both_exist(monkeypatch, tmp_path):
    """When both paths have a db, XDG wins (newer install)."""
    from superharness.engine.db import get_connection, init_db
    state_dir = str(tmp_path / "xdg_state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)

    project = str(tmp_path / "dualproject")
    legacy_dir = os.path.join(project, ".superharness")
    os.makedirs(legacy_dir)
    legacy_db = os.path.join(legacy_dir, "state.sqlite3")
    conn0 = sqlite3.connect(legacy_db)
    conn0.execute("CREATE TABLE IF NOT EXISTS marker (id INTEGER PRIMARY KEY)")
    conn0.execute("INSERT INTO marker VALUES (999)")
    conn0.commit()
    conn0.close()

    xdg_db = resolve_xdg_state_db_path(project)
    os.makedirs(os.path.dirname(xdg_db), exist_ok=True)
    conn1 = sqlite3.connect(xdg_db)
    conn1.execute("CREATE TABLE IF NOT EXISTS marker (id INTEGER PRIMARY KEY)")
    conn1.execute("INSERT INTO marker VALUES (1)")
    conn1.commit()
    conn1.close()

    conn = get_connection(project)
    row = conn.execute("SELECT id FROM marker").fetchone()
    conn.close()
    assert row[0] == 1, "XDG db (marker=1) should be opened, not legacy (marker=999)"
