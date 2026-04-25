from __future__ import annotations

import pytest

from superharness.engine import tasks_dao
from superharness.engine.tasks_dao import TaskRow
from superharness.engine.state_errors import ConcurrencyError

T0 = "2026-01-01T00:00:00Z"


def _task(id="task-1", status="todo", **kwargs) -> TaskRow:
    return TaskRow(
        id=id,
        title="Test task",
        owner="claude-code",
        status=status,
        effort="medium",
        project_path=None,
        development_method=None,
        acceptance_criteria=["must work"],
        test_types=["unit"],
        out_of_scope=[],
        definition_of_done=["tests pass"],
        context="some context",
        tdd={"red": "write test", "green": "implement", "refactor": "clean up"},
        version=1,
        created_at=T0,
        plan_proposed_at=None,
        plan_approved_at=None,
        in_progress_at=None,
        report_ready_at=None,
        done_at=None,
        cancelled_at=None,
        blocked_by=[],
        **kwargs,
    )


def test_upsert_and_get(db_conn):
    row = tasks_dao.upsert(db_conn, _task())
    assert row.id == "task-1"
    assert row.acceptance_criteria == ["must work"]
    assert row.tdd == {"red": "write test", "green": "implement", "refactor": "clean up"}

    fetched = tasks_dao.get(db_conn, "task-1")
    assert fetched is not None
    assert fetched.id == "task-1"


def test_get_none(db_conn):
    assert tasks_dao.get(db_conn, "missing") is None


def test_upsert_updates_version(db_conn):
    tasks_dao.upsert(db_conn, _task())
    row1 = tasks_dao.get(db_conn, "task-1")
    tasks_dao.upsert(db_conn, _task(status="in_progress"))
    row2 = tasks_dao.get(db_conn, "task-1")
    assert row2.version > row1.version
    assert row2.status == "in_progress"


def test_get_all_filter_status(db_conn):
    tasks_dao.upsert(db_conn, _task("t1", status="todo"))
    tasks_dao.upsert(db_conn, _task("t2", status="done"))
    result = tasks_dao.get_all(db_conn, status="todo")
    assert [r.id for r in result] == ["t1"]


def test_update_optimistic_concurrency(db_conn):
    tasks_dao.upsert(db_conn, _task())
    row = tasks_dao.get(db_conn, "task-1")
    updated = tasks_dao.update(db_conn, "task-1", version=row.version, changes={"status": "done"})
    assert updated.status == "done"


def test_update_concurrency_error(db_conn):
    tasks_dao.upsert(db_conn, _task())
    with pytest.raises(ConcurrencyError):
        tasks_dao.update(db_conn, "task-1", version=999, changes={"status": "done"})


def test_set_dependencies(db_conn):
    tasks_dao.upsert(db_conn, _task("t1"))
    tasks_dao.upsert(db_conn, _task("t2"))
    tasks_dao.set_dependencies(db_conn, "t2", ["t1"])
    row = tasks_dao.get(db_conn, "t2")
    assert row.blocked_by == ["t1"]

    # Replace with empty
    tasks_dao.set_dependencies(db_conn, "t2", [])
    row = tasks_dao.get(db_conn, "t2")
    assert row.blocked_by == []


def test_get_unblocked(db_conn):
    tasks_dao.upsert(db_conn, _task("t1", status="done"))
    tasks_dao.upsert(db_conn, _task("t2", status="todo"))
    tasks_dao.set_dependencies(db_conn, "t2", ["t1"])

    unblocked = tasks_dao.get_unblocked(db_conn)
    ids = [r.id for r in unblocked]
    assert "t2" in ids  # t1 is done, so t2 is unblocked


def test_get_unblocked_with_pending_dep(db_conn):
    tasks_dao.upsert(db_conn, _task("t1", status="todo"))
    tasks_dao.upsert(db_conn, _task("t2", status="todo"))
    tasks_dao.set_dependencies(db_conn, "t2", ["t1"])

    unblocked = tasks_dao.get_unblocked(db_conn)
    ids = [r.id for r in unblocked]
    assert "t2" not in ids  # t1 not done, so t2 is blocked
    assert "t1" in ids      # t1 has no deps, so it's unblocked
