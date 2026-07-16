"""Iteration 2: `shux task link` — set/clear issue_url on an existing task."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest


def _setup_project(tmp_path: Path, issue_url: str | None = None) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(project))
    try:
        init_db(conn)
        row = TaskRow(
            id="t-link-test",
            title="Link test task",
            owner="claude-code",
            status="todo",
            effort="medium",
            project_path=str(project),
            development_method="tdd",
            acceptance_criteria=[],
            test_types=[],
            out_of_scope=[],
            definition_of_done=[],
            context=None,
            tdd=None,
            version=1,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            issue_url=issue_url,
        )
        tasks_dao.upsert(conn, row)
        conn.commit()
    finally:
        conn.close()
    return project


def _get_issue_url(project: Path, task_id: str) -> str | None:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    conn = get_connection(str(project))
    try:
        init_db(conn)
        row = tasks_dao.get(conn, task_id)
        assert row is not None
        return row.issue_url
    finally:
        conn.close()


def test_link_sets_url_on_existing_task(tmp_path: Path) -> None:
    from superharness.commands.task import link

    project = _setup_project(tmp_path)
    rc = link(str(project), "t-link-test", url="https://github.com/o/r/issues/9")
    assert rc == 0
    assert _get_issue_url(project, "t-link-test") == "https://github.com/o/r/issues/9"


def test_link_clear_removes_url(tmp_path: Path) -> None:
    from superharness.commands.task import link

    project = _setup_project(tmp_path, issue_url="https://github.com/o/r/issues/9")
    rc = link(str(project), "t-link-test", clear=True)
    assert rc == 0
    assert _get_issue_url(project, "t-link-test") is None


def test_link_rejects_invalid_url(tmp_path: Path) -> None:
    from superharness.commands.task import link

    project = _setup_project(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        link(str(project), "t-link-test", url="not-a-url")
    assert exc_info.value.code != 0
    assert _get_issue_url(project, "t-link-test") is None


def test_link_missing_task_errors(tmp_path: Path) -> None:
    from superharness.commands.task import link

    project = _setup_project(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        link(str(project), "nonexistent-task", url="https://github.com/o/r/issues/9")
    assert exc_info.value.code != 0
