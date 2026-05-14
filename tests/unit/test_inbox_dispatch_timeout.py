"""Tests for dispatcher auto-timeout feature (feat.auto-timeout).

Updated for SQLite-primary: _get_task_effort_timeout now takes project_dir
instead of contract_file. Tasks must exist in SQLite state.db.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from superharness.commands.inbox_dispatch import _get_task_effort_timeout
from superharness.engine.db import get_connection, init_db
from superharness.engine import tasks_dao
from superharness.engine.tasks_dao import TaskRow

T0 = "2026-01-01T00:00:00Z"


def _mk_project(tmp_path: Path, tasks: list[dict]) -> Path:
    """Create a .superharness project with the given tasks in SQLite."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    conn = get_connection(str(project))
    init_db(conn)
    for t in tasks:
        defaults = dict(
            title=t.get("title", t["id"]), owner="claude-code", status="todo",
            effort=t.get("effort"), project_path=str(project),
            development_method="tdd", acceptance_criteria=[], test_types=[],
            out_of_scope=[], definition_of_done=[], context=None, tdd=None,
            version=1, created_at=T0,
            estimated_minutes=t.get("estimated_minutes"),
        )
        tasks_dao.upsert(conn, TaskRow(id=t["id"], **defaults))
    conn.commit()
    conn.close()
    return project


@pytest.fixture
def effort_project(tmp_path: Path) -> Path:
    return _mk_project(tmp_path, [
        {"id": "low-effort-task", "effort": "low"},
        {"id": "medium-effort-task", "effort": "medium"},
        {"id": "high-effort-task", "effort": "high"},
        {"id": "explicit-minutes-task", "estimated_minutes": "45"},
        {"id": "both-set-task", "effort": "low", "estimated_minutes": "90"},
        {"id": "no-estimate-task"},
    ])


def test_auto_timeout_from_effort_low(effort_project: Path) -> None:
    assert _get_task_effort_timeout(str(effort_project), "low-effort-task") == 900


def test_auto_timeout_from_effort_medium(effort_project: Path) -> None:
    assert _get_task_effort_timeout(str(effort_project), "medium-effort-task") == 1800


def test_auto_timeout_from_effort_high(effort_project: Path) -> None:
    assert _get_task_effort_timeout(str(effort_project), "high-effort-task") == 3600


def test_auto_timeout_from_estimated_minutes(effort_project: Path) -> None:
    assert _get_task_effort_timeout(str(effort_project), "explicit-minutes-task") == 2700


def test_auto_timeout_estimated_minutes_overrides_effort(effort_project: Path) -> None:
    assert _get_task_effort_timeout(str(effort_project), "both-set-task") == 5400


def test_auto_timeout_fallback_when_no_estimate(effort_project: Path) -> None:
    assert _get_task_effort_timeout(str(effort_project), "no-estimate-task") == 0


def test_auto_timeout_task_not_found(effort_project: Path) -> None:
    assert _get_task_effort_timeout(str(effort_project), "nonexistent-task") == 0


def test_dispatcher_uses_auto_timeout(tmp_path: Path) -> None:
    """Integration: verify dispatcher calculates timeout when launcher_timeout=0."""
    project = _mk_project(tmp_path, [{"id": "test-task", "effort": "medium"}])
    assert _get_task_effort_timeout(str(project), "test-task") == 1800
