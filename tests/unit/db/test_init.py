from __future__ import annotations

import sqlite3
import os
from pathlib import Path

import pytest
from superharness.engine.state_errors import ConnectionError

def test_db_file_created(tmp_path: Path):
    from superharness.engine.db import get_connection
    project = tmp_path
    sh_dir = project / ".superharness"
    sh_dir.mkdir()
    
    db_path = sh_dir / "state.sqlite3"
    assert not db_path.exists()
    
    conn = get_connection(str(project))
    try:
        assert db_path.exists()
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
    
    # User version
    cursor = db_conn.execute("PRAGMA user_version")
    assert cursor.fetchone()[0] == 1

def test_schema_migrations_row(db_conn: sqlite3.Connection):
    cursor = db_conn.execute("SELECT version FROM schema_migrations WHERE version=1")
    assert cursor.fetchone() is not None

def test_idempotency(db_conn: sqlite3.Connection):
    from superharness.engine.db import init_db
    # Should not raise even if called again
    init_db(db_conn)
    init_db(db_conn)
    
    cursor = db_conn.execute("SELECT count(*) FROM schema_migrations")
    assert cursor.fetchone()[0] == 1

def test_sqlite_version_check(monkeypatch, tmp_path: Path):
    import sqlite3
    # Force a low version for testing
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 34, 0))
    
    from superharness.engine.db import get_connection
    project = tmp_path
    (project / ".superharness").mkdir()
    
    with pytest.raises(ConnectionError, match="SQLite version 3.35.0 or higher required"):
        get_connection(str(project))
