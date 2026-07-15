"""Iteration 1: issue_url storage — migration v30, TaskRow round-trip, validation."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

T0 = "2026-01-01T00:00:00Z"


def _connect(tmp_path):
    from superharness.engine.db import get_connection, init_db
    (tmp_path / ".superharness").mkdir(exist_ok=True)
    conn = get_connection(str(tmp_path))
    init_db(conn)
    return conn


def _task(id="task-1", **kwargs):
    from superharness.engine.tasks_dao import TaskRow
    return TaskRow(
        id=id,
        title="Test task",
        owner="claude-code",
        status="todo",
        effort="medium",
        project_path=None,
        development_method=None,
        acceptance_criteria=[],
        test_types=[],
        out_of_scope=[],
        definition_of_done=[],
        context=None,
        tdd=None,
        version=1,
        created_at=T0,
        blocked_by=[],
        **kwargs,
    )


def test_upsert_roundtrips_issue_url(tmp_path):
    from superharness.engine import tasks_dao

    conn = _connect(tmp_path)
    try:
        tasks_dao.upsert(conn, _task(issue_url="https://github.com/o/r/issues/5"))
        fetched = tasks_dao.get(conn, "task-1")
        assert fetched.issue_url == "https://github.com/o/r/issues/5"
    finally:
        conn.close()


def test_row_to_task_defaults_none_on_legacy_db(tmp_path):
    from superharness.engine import tasks_dao

    conn = _connect(tmp_path)
    try:
        tasks_dao.upsert(conn, _task())
        fetched = tasks_dao.get(conn, "task-1")
        assert fetched.issue_url is None
    finally:
        conn.close()


def test_validate_issue_url_accepts_github_and_gitlab():
    from superharness.commands.task import _validate_issue_url

    assert _validate_issue_url("https://github.com/o/r/issues/5") == "https://github.com/o/r/issues/5"
    assert (
        _validate_issue_url("https://gitlab.gs/o/r/-/issues/5")
        == "https://gitlab.gs/o/r/-/issues/5"
    )


def test_validate_issue_url_rejects_non_http():
    from superharness.commands.task import _validate_issue_url

    with pytest.raises(ValueError):
        _validate_issue_url("ftp://x")
    with pytest.raises(ValueError):
        _validate_issue_url("not-a-url")


def test_contracttask_accepts_issue_url():
    from superharness.engine.schemas import ContractTask

    t = ContractTask(id="t1", status="todo", issue_url="https://github.com/o/r/issues/1")
    assert t.issue_url == "https://github.com/o/r/issues/1"
