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


def _make_task_row(**overrides):
    from superharness.engine.tasks_dao import TaskRow

    base = dict(
        id="t-parent", title="Parent", owner="claude-code", status="todo",
        effort="medium", project_path=None, development_method=None,
        acceptance_criteria=[], test_types=[], out_of_scope=[], definition_of_done=[],
        context=None, tdd=None, version=1, created_at="2026-01-01T00:00:00Z",
    )
    base.update(overrides)
    return TaskRow(**base)


def test_delete_parent_task_with_subtask_does_not_raise_and_orphans_subtask(tmp_path):
    """v33 RED: tasks.parent_id currently has FOREIGN KEY REFERENCES tasks(id)
    with no ON DELETE clause. With foreign_keys=ON (set on every connection),
    SQLite's default action is NO ACTION, which behaves like RESTRICT — deleting
    a parent task that still has subtasks raises sqlite3.IntegrityError, and
    `shux task delete` (commands/task.py:293) does not catch it.

    After the fix, ON DELETE SET NULL must let the delete succeed and orphan
    the subtask (parent_id -> NULL) instead of blocking or cascading."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.commands import task as task_cmd

    project = str(tmp_path / "proj")
    conn = get_connection(project)
    init_db(conn, project_dir=project)
    tasks_dao.upsert(conn, _make_task_row(id="t-parent", title="Parent"))
    tasks_dao.upsert(conn, _make_task_row(id="t-child", title="Child", parent_id="t-parent"))
    conn.commit()
    conn.close()

    task_cmd.delete(project, "t-parent")  # must not raise IntegrityError

    conn = get_connection(project)
    child = tasks_dao.get(conn, "t-child")
    conn.close()
    assert child is not None, "subtask must survive the parent delete, not cascade-delete"
    assert child.parent_id is None, "subtask must be orphaned (parent_id -> NULL), not left dangling"


def test_delete_task_nulls_task_id_in_failures_decisions_ledger(tmp_path):
    """v33 RED: failures/decisions/ledger.task_id have no FK today, so deleting
    a task leaves dangling task_id references in those audit tables (silent
    data debt, no crash). After the fix, ON DELETE SET NULL must null out
    task_id in all three tables, preserving the audit rows themselves."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.commands import task as task_cmd

    project = str(tmp_path / "proj")
    conn = get_connection(project)
    init_db(conn, project_dir=project)
    tasks_dao.upsert(conn, _make_task_row(id="t-audit", title="Audited"))
    conn.execute(
        "INSERT INTO failures (task_id, agent, pattern, error_snippet, created_at) "
        "VALUES ('t-audit', 'claude-code', 'timeout', 'boom', '2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO decisions (agent, task_id, decision, reason, alternatives, created_at) "
        "VALUES ('claude-code', 't-audit', 'use X', 'because', '[]', '2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO ledger (task_id, agent, action, details, created_at) "
        "VALUES ('t-audit', 'claude-code', 'created', '{}', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    task_cmd.delete(project, "t-audit")

    conn = get_connection(project)
    failure_task_id = conn.execute("SELECT task_id FROM failures WHERE pattern='timeout'").fetchone()[0]
    decision_task_id = conn.execute("SELECT task_id FROM decisions WHERE decision='use X'").fetchone()[0]
    ledger_task_id = conn.execute("SELECT task_id FROM ledger WHERE action='created'").fetchone()[0]
    conn.close()

    assert failure_task_id is None, "failures.task_id must be nulled by ON DELETE SET NULL, not left dangling"
    assert decision_task_id is None, "decisions.task_id must be nulled by ON DELETE SET NULL, not left dangling"
    assert ledger_task_id is None, "ledger.task_id must be nulled by ON DELETE SET NULL, not left dangling"


def test_heal_drift_generalizes_beyond_v25_agent_heartbeats(tmp_path):
    """v33 RED: _heal_known_migration_drift only checks agent_heartbeats/v25.
    The same _column_exists row_factory bug could have skipped any
    _add_column_if_missing call in any migration. Simulate v30's `tasks`
    table missing `issue_url` despite user_version claiming v30+ applied,
    and assert the generalized heal repairs it too — a different table and a
    different migration than the one already-known agent_heartbeats/v25 case."""
    from superharness.engine.db import CURRENT_SCHEMA_VERSION, init_db

    project = str(tmp_path / "proj")
    db_path = _make_legacy_db(project)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Minimal tasks table as of v1, missing every column added by later
    # ALTER-based migrations (in particular v30's issue_url).
    conn.execute("""
        CREATE TABLE tasks (
            id     TEXT PRIMARY KEY,
            title  TEXT NOT NULL,
            status TEXT NOT NULL,
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

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    conn.close()
    assert "issue_url" in cols, f"generalized heal did not repair tasks.issue_url: {cols}"
