from __future__ import annotations

import sqlite3
import os
import shutil
import pytest
from unittest.mock import patch
from pathlib import Path

from superharness.engine.db import get_connection, init_db

def test_init_db_is_idempotent(tmp_path):
    project = tmp_path
    sh_dir = project / ".superharness"
    sh_dir.mkdir(exist_ok=True)
    conn = get_connection(str(project))
    
    # First call (initially empty)
    init_db(conn, str(project))
    
    # Second call (already migrated)
    # This should not raise OperationalError (duplicate column)
    init_db(conn, str(project))
    conn.close()

def test_partial_v3_recovers(tmp_path):
    project = tmp_path
    sh_dir = project / ".superharness"
    sh_dir.mkdir(exist_ok=True)
    conn = get_connection(str(project))
    
    # Get to version 2
    from superharness.engine import db
    with patch("superharness.engine.db.CURRENT_SCHEMA_VERSION", 2):
        init_db(conn, str(project))
    
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    
    # Simulate partial migration: column 'verified' exists but version is still 2.
    conn.execute("ALTER TABLE tasks ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    
    # Now call init_db. It should detect version 2 < 3, run v3, 
    # but handle the fact that 'verified' is already there.
    init_db(conn, str(project))
    
    # Check if other v3 columns exist
    info = [r["name"] for r in conn.execute("PRAGMA table_info(tasks)")]
    assert "verified" in info
    assert "verified_at" in info
    assert "verified_by" in info
    
    # Check version
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    conn.close()

def test_migration_creates_backup(tmp_path):
    project = tmp_path
    sh_dir = project / ".superharness"
    sh_dir.mkdir(exist_ok=True)
    
    conn = get_connection(str(project))
    
    # To test backups, we need to go through multiple versions
    # and init_db needs to know the project path.
    # Note: init_db might need to be modified to take project_dir.
    
    # Let's try running it.
    init_db(conn, str(project))
    
    assert (sh_dir / "state.sqlite3.bak.v1").exists()
    assert (sh_dir / "state.sqlite3.bak.v2").exists()
    conn.close()

def test_fk_violation_rolls_back(tmp_path):
    project = tmp_path
    sh_dir = project / ".superharness"
    sh_dir.mkdir(exist_ok=True)
    conn = get_connection(str(project))
    
    from superharness.engine import db
    
    def failing_v3(c):
        c.execute("ALTER TABLE tasks ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
        raise RuntimeError("mid-migration crash")
        
    with patch("superharness.engine.db._MIGRATIONS", [db._migration_v1, db._migration_v2, failing_v3]):
        # We first need to get to v2 successfully
        with patch("superharness.engine.db.CURRENT_SCHEMA_VERSION", 2):
            init_db(conn, str(project))
        
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        
        # Now try to go to v3 and fail
        with patch("superharness.engine.db.CURRENT_SCHEMA_VERSION", 3):
            with pytest.raises(RuntimeError, match="mid-migration crash"):
                init_db(conn, str(project))
                
        # Assertion: user_version stays at 2; the first ALTER is not persisted (savepoint rollback).
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        info = [r["name"] for r in conn.execute("PRAGMA table_info(tasks)")]
        assert "verified" not in info
        
    conn.close()
