"""Status-transition hard guard (arch A2, partial — no SQLite CHECK constraint
rebuild; the state machine is still enforced in application code only, but a
hard floor now exists at the DAO layer).

Two independent layers:
  1. tasks_dao.update() rejects any `status` value outside the canonical
     ALL_STATUSES enum (VALID_STATUSES), even under force=True callers that
     bypass state_writer.validate_status_transition()'s legal-edge graph.
  2. state_writer.set_task_status() logs an illegal *transition* (a known
     status to a status that is not reachable from it) via logger.warning
     instead of print(..., file=sys.stderr).
"""
from __future__ import annotations

import logging

import pytest

from superharness.engine import db as db_module
from superharness.engine import state_writer, tasks_dao
from superharness.engine.next_action import ALL_STATUSES
from superharness.engine.state_errors import StateError


def _make_task(conn, task_id: str = "t-guard", status: str = "todo") -> None:
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at, "
        "acceptance_criteria, test_types, out_of_scope, definition_of_done) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (task_id, "Guard Test Task", "claude-code", status, "2026-07-19T00:00:00Z",
         "[]", "[]", "[]", "[]"),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# tasks_dao.update — VALID_STATUSES floor
# ---------------------------------------------------------------------------

def test_update_rejects_garbage_status(tmp_path):
    project_dir = str(tmp_path)
    conn = db_module.get_connection(project_dir)
    db_module.init_db(conn, project_dir)
    _make_task(conn)

    row = tasks_dao.get(conn, "t-guard")
    with pytest.raises(ValueError, match="Invalid status"):
        tasks_dao.update(conn, "t-guard", row.version, {"status": "banana"})


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_update_accepts_every_canonical_status(tmp_path, status):
    project_dir = str(tmp_path)
    conn = db_module.get_connection(project_dir)
    db_module.init_db(conn, project_dir)
    _make_task(conn)

    row = tasks_dao.get(conn, "t-guard")
    updated = tasks_dao.update(conn, "t-guard", row.version, {"status": status})
    assert updated.status == status


def test_update_without_status_key_is_unaffected(tmp_path):
    """The guard only inspects changes that actually set 'status'."""
    project_dir = str(tmp_path)
    conn = db_module.get_connection(project_dir)
    db_module.init_db(conn, project_dir)
    _make_task(conn)

    row = tasks_dao.get(conn, "t-guard")
    updated = tasks_dao.update(conn, "t-guard", row.version, {"owner": "codex-cli"})
    assert updated.owner == "codex-cli"
    assert updated.status == "todo"


# ---------------------------------------------------------------------------
# state_writer.set_task_status — illegal transition logs a warning, not print
# ---------------------------------------------------------------------------

def test_invalid_transition_logs_warning_not_print(tmp_path, caplog, monkeypatch, capsys):
    project_dir = str(tmp_path)

    # Known pollution bug (arch/logging): logging_utils.get_logger()
    # unconditionally sets logging.getLogger("superharness").propagate =
    # False process-wide the first time anything calls it, which silently
    # breaks caplog for every "superharness.*" child logger for the rest
    # of the test session. Force propagation back on for this test.
    monkeypatch.setattr(logging.getLogger("superharness"), "propagate", True)

    conn = db_module.get_connection(project_dir)
    db_module.init_db(conn, project_dir)
    _make_task(conn, task_id="t-transition", status="done")  # terminal status

    with caplog.at_level(logging.WARNING, logger="superharness.engine.state_writer"):
        result = state_writer.set_task_status(project_dir, "t-transition", "todo")

    assert result is False
    captured = capsys.readouterr()
    assert "status transition rejected" not in captured.err, (
        "illegal transition must no longer be printed to stderr"
    )
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("status transition rejected" in w for w in warnings), (
        f"expected a logged warning for the rejected transition, got: {warnings}"
    )
