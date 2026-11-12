"""An automatic plan approval must leave an audit row naming actor and policy."""

from __future__ import annotations

from pathlib import Path

import pytest

# Reuse the synthetic project builders of the sibling auto-approval tests.
from test_default_plan_auto_approval import (  # type: ignore[import-not-found]
    _TASK_ID,
    _add_plan_handoff,
    _make_project,
)

from superharness.commands import task as task_cmd
from superharness.engine import ledger_dao, tasks_dao
from superharness.engine.db import get_connection, init_db
from superharness.engine.state_errors import StateError


def _propose(project: Path, monkeypatch) -> None:
    monkeypatch.setattr(task_cmd, "_enqueue_for_implementation", lambda *a, **k: None)
    task_cmd.status_update(str(project), _TASK_ID, "plan_proposed", actor="claude-code")


def _status(project: Path) -> str:
    conn = get_connection(str(project))
    try:
        init_db(conn)
        row = tasks_dao.get(conn, _TASK_ID)
        assert row is not None
        return row.status
    finally:
        conn.close()


def _approval_rows(project: Path) -> list[ledger_dao.LedgerRow]:
    conn = get_connection(str(project))
    try:
        init_db(conn)
        rows = conn.execute(
            "SELECT id FROM ledger WHERE task_id = ? AND action = 'plan_auto_approved'",
            (_TASK_ID,),
        ).fetchall()
        recent = ledger_dao.get_recent(conn, limit=50)
    finally:
        conn.close()
    wanted = {r["id"] for r in rows}
    return [r for r in recent if r.id in wanted]


def test_auto_approve_writes_ledger_row(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path, "autonomy: ai_driven\n")
    _add_plan_handoff(project)
    _propose(project, monkeypatch)

    rows = _approval_rows(project)
    assert _status(project) == "plan_approved"
    assert len(rows) == 1
    assert rows[0].agent == "ai-autonomy"
    assert rows[0].task_id == _TASK_ID


def test_auto_approve_row_names_policy_source_file_profile(
    tmp_path: Path, monkeypatch
) -> None:
    project = _make_project(tmp_path, "autonomy: ai_driven\n")
    _add_plan_handoff(project)
    _propose(project, monkeypatch)

    (row,) = _approval_rows(project)
    assert row.details is not None
    assert "profile=file" in row.details["policy_source"]
    assert "autonomy=ai_driven" in row.details["policy_source"]


def test_absent_profile_writes_no_approval_row(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path, None)
    _add_plan_handoff(project)
    _propose(project, monkeypatch)

    assert _status(project) == "plan_proposed"
    assert _approval_rows(project) == []


def test_auto_approve_row_names_policy_source_explicit_key(
    tmp_path: Path, monkeypatch
) -> None:
    project = _make_project(tmp_path, "auto_approve_plans: true\n")
    _add_plan_handoff(project)
    _propose(project, monkeypatch)

    (row,) = _approval_rows(project)
    assert row.details is not None
    assert "profile=explicit" in row.details["policy_source"]


def test_blocked_auto_approve_writes_no_row(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path, None)
    _add_plan_handoff(project, valid=False)
    _propose(project, monkeypatch)

    assert _status(project) == "plan_proposed"
    assert _approval_rows(project) == []


def test_ledger_write_failure_does_not_approve_silently(
    tmp_path: Path, monkeypatch
) -> None:
    """Fail loud: if the audit row cannot be written the plan is not approved."""
    project = _make_project(tmp_path, "autonomy: ai_driven\n")
    _add_plan_handoff(project)

    def failing_record(*args, **kwargs):
        raise StateError("ledger unavailable")

    monkeypatch.setattr(ledger_dao, "record", failing_record)
    with pytest.raises(StateError, match="ledger unavailable"):
        _propose(project, monkeypatch)

    assert _status(project) == "plan_proposed"


def test_auto_approve_message_names_policy_source(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = _make_project(tmp_path, "autonomy: ai_driven\n")
    _add_plan_handoff(project)
    _propose(project, monkeypatch)

    assert "profile=file" in capsys.readouterr().out
