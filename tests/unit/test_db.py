"""Iter 13 RED tests: DB backup, PRAGMA, and schema hardening."""
from __future__ import annotations

import os
import sqlite3


def _make_legacy_db(project_dir: str) -> str:
    """Create a legacy .superharness/state.sqlite3 at the project path."""
    sh = os.path.join(project_dir, ".superharness")
    os.makedirs(sh, exist_ok=True)
    db_path = os.path.join(sh, "state.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()
    return db_path


def test_init_db_backs_up_live_db(tmp_path):
    """When init_db runs a migration, it must create a backup of the pre-migration db.

    RED: init_db(conn, project_dir) calls _backup_db only when a migration runs.
    The test seeds a db at version 0 so migration v1 fires and backup is created.
    """
    from superharness.engine.db import CURRENT_SCHEMA_VERSION

    project = str(tmp_path / "proj")
    db_path = _make_legacy_db(project)

    # Open the db and force schema version to 0 so a migration will run
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    from superharness.engine.db import init_db
    init_db(conn, project_dir=project)
    conn.close()

    # Verify a backup file was created
    backup_files = [f for f in os.listdir(os.path.join(project, ".superharness"))
                    if f.endswith(".bak.v0") or ".bak.v" in f]
    assert backup_files, (
        f"No backup file found in .superharness/ after migration. "
        f"Files present: {os.listdir(os.path.join(project, '.superharness'))}. "
        "init_db must call _backup_db when project_dir is supplied and a migration runs."
    )


def test_get_connection_sets_wal_and_fk(tmp_path):
    """get_connection must set WAL journal mode and foreign_keys=ON."""
    project = str(tmp_path / "proj")
    _make_legacy_db(project)

    from superharness.engine.db import get_connection
    conn = get_connection(project)
    try:
        jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        conn.close()

    assert jm == "wal", f"Expected journal_mode=wal, got {jm!r}"
    assert fk == 1, f"Expected foreign_keys=1 (ON), got {fk!r}"
