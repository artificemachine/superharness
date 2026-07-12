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


def test_init_db_heals_agent_heartbeats_missing_v25_columns(tmp_path):
    """A DB can claim v25+ applied (schema_migrations + PRAGMA user_version)
    while agent_heartbeats is missing the columns v25 was supposed to add —
    a real, observed historical failure mode from before _column_exists was
    fixed to handle row_factory=None. init_db() must self-heal this: detect
    the drift and re-run the missing ALTER TABLEs without re-running the
    whole migration (schema_migrations/user_version already correctly claim
    v25 done — don't touch them)."""
    from superharness.engine.db import CURRENT_SCHEMA_VERSION, init_db

    project = str(tmp_path / "proj")
    db_path = _make_legacy_db(project)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Simulate the base agent_heartbeats table (as created by v18) with none
    # of v25's columns, but user_version/schema_migrations already claiming
    # every migration through CURRENT_SCHEMA_VERSION is applied.
    conn.execute("""
        CREATE TABLE agent_heartbeats (
            id INTEGER PRIMARY KEY,
            agent TEXT NOT NULL,
            task_id TEXT,
            status TEXT NOT NULL DEFAULT 'alive',
            pid INTEGER,
            updated_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    for v in range(1, CURRENT_SCHEMA_VERSION + 1):
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, '2026-01-01T00:00:00Z')",
            (v,),
        )
    conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
    conn.commit()

    init_db(conn, project_dir=project)

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(agent_heartbeats)").fetchall()}
    conn.close()

    for expected in ("runtime", "active_task", "next_wake_at", "written_at",
                      "tokens_used", "tokens_limit", "cost_usd"):
        assert expected in cols, f"init_db did not heal missing column {expected!r}: {cols}"


def test_init_db_heal_is_noop_when_columns_already_present(tmp_path):
    """The heal check must not error or duplicate work on an already-correct
    DB — it should just observe the columns are present and do nothing."""
    from superharness.engine.db import init_db

    project = str(tmp_path / "proj")
    db_path = _make_legacy_db(project)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn, project_dir=project)  # normal migration path populates everything

    # Run init_db again — heal check must be a safe no-op, not raise
    init_db(conn, project_dir=project)

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(agent_heartbeats)").fetchall()}
    conn.close()
    assert "runtime" in cols
