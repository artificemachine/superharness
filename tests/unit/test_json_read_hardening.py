"""JSON-read hardening (arch A4) + idempotent index creation (arch A6).

tasks_dao's row-mapping path parses several JSON-in-TEXT columns
(acceptance_criteria, test_types, out_of_scope, definition_of_done, tdd).
A single malformed row must degrade to a default value, not raise and
break bulk reads like `shux contract`. The warning logged on failure must
name the offending task and column so an operator can find and repair it.

Also covers arch A6: two CREATE INDEX statements in db.py's migration v1
(idx_failures_task, idx_failures_agent_pattern) were missing
IF NOT EXISTS, the only ones of ~30 index statements without it — running
init_db twice on the same connection raised "index already exists".
"""
from __future__ import annotations

import logging

from superharness.engine import db as db_module
from superharness.engine import tasks_dao


def _seed_task_with_raw_json(conn, task_id: str, acceptance_criteria_raw: str) -> None:
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at, "
        "acceptance_criteria, test_types, out_of_scope, definition_of_done) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            task_id,
            "Malformed JSON Task",
            "claude-code",
            "todo",
            "2026-07-19T00:00:00Z",
            acceptance_criteria_raw,
            "[]",
            "[]",
            "[]",
        ),
    )
    conn.commit()


def test_malformed_json_column_returns_default_not_raise(tmp_path, caplog):
    project_dir = str(tmp_path)
    conn = db_module.get_connection(project_dir)
    db_module.init_db(conn, project_dir)

    _seed_task_with_raw_json(conn, "t-malformed", "{not valid json")

    with caplog.at_level(logging.WARNING, logger="superharness.engine.tasks_dao"):
        task = tasks_dao.get(conn, "t-malformed")

    assert task is not None
    assert task.acceptance_criteria == [], (
        "malformed JSON must degrade to the default value, not raise"
    )


def test_malformed_json_warning_names_task_and_column(tmp_path, caplog):
    project_dir = str(tmp_path)
    conn = db_module.get_connection(project_dir)
    db_module.init_db(conn, project_dir)

    _seed_task_with_raw_json(conn, "t-malformed-2", "[[[broken")

    with caplog.at_level(logging.WARNING, logger="superharness.engine.tasks_dao"):
        tasks_dao.get(conn, "t-malformed-2")

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("t-malformed-2" in w for w in warnings), (
        f"no warning named the task id 't-malformed-2': {warnings}"
    )
    assert any("acceptance_criteria" in w for w in warnings), (
        f"no warning named the column 'acceptance_criteria': {warnings}"
    )


def test_well_formed_json_column_still_parses_normally(tmp_path):
    project_dir = str(tmp_path)
    conn = db_module.get_connection(project_dir)
    db_module.init_db(conn, project_dir)

    _seed_task_with_raw_json(conn, "t-ok", '["criterion 1", "criterion 2"]')

    task = tasks_dao.get(conn, "t-ok")
    assert task.acceptance_criteria == ["criterion 1", "criterion 2"]


# ---------------------------------------------------------------------------
# arch A6 — CREATE INDEX IF NOT EXISTS for idx_failures_*
# ---------------------------------------------------------------------------

def test_failures_indexes_are_idempotent(tmp_path):
    """_migration_v1 (which creates idx_failures_task/idx_failures_agent_pattern)
    must be safe to run twice against the same connection without raising
    'index already exists'.

    init_db() itself only re-runs migrations with version > the recorded
    user_version, so it won't naturally re-invoke _migration_v1 on an
    already-migrated DB and wouldn't exercise this bug. Calling the
    migration function directly is the only way to reproduce the failure
    mode CREATE INDEX (without IF NOT EXISTS) causes on a rebuild.
    """
    project_dir = str(tmp_path)
    conn = db_module.get_connection(project_dir)
    db_module.init_db(conn, project_dir)

    # Must not raise sqlite3.OperationalError: index idx_failures_task already exists
    db_module._migration_v1(conn)
