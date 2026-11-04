"""The human actor 'owner' may approve or reject a plan on any agent's task.

Every other transition on another agent's task stays forbidden for 'owner',
and agents still cannot update each other's tasks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _project_with_task(tmp_path: Path, task_id: str, status: str, owner: str) -> str:
    (tmp_path / ".superharness").mkdir()
    from superharness.engine.db import get_connection, init_db

    conn = get_connection(str(tmp_path))
    try:
        init_db(conn)
        conn.execute(
            "INSERT INTO tasks (id, title, owner, status, created_at, updated_at, "
            "acceptance_criteria, test_types, out_of_scope, definition_of_done) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (task_id, task_id, owner, status, _now(), _now(), "[]", "[]", "[]", "[]"),
        )
        conn.commit()
    finally:
        conn.close()
    return str(tmp_path)


def _status_of(project: str, task_id: str) -> str:
    from superharness.engine.db import get_connection

    conn = get_connection(project)
    try:
        return conn.execute(
            "SELECT status FROM tasks WHERE id=?", (task_id,)
        ).fetchone()["status"]
    finally:
        conn.close()


@pytest.mark.parametrize("target", ["plan_approved", "todo"])
def test_owner_actor_can_decide_a_plan_on_an_agent_task(tmp_path, target):
    project = _project_with_task(tmp_path, "t-plan", "plan_proposed", "claude-code")

    from superharness.commands.task import status_update

    rc = status_update(
        project, "t-plan", target, "owner", summary="owner decision in chat"
    )
    assert rc == 0
    assert _status_of(project, "t-plan") == target


def test_owner_actor_cannot_make_other_transitions_on_an_agent_task(tmp_path):
    project = _project_with_task(tmp_path, "t-prog", "in_progress", "claude-code")

    from superharness.commands.task import status_update

    with pytest.raises(SystemExit) as exc_info:
        status_update(project, "t-prog", "stopped", "owner", reason="no")
    assert exc_info.value.code == 1
    assert _status_of(project, "t-prog") == "in_progress"


def test_agent_actor_still_cannot_update_another_agents_task(tmp_path):
    project = _project_with_task(tmp_path, "t-other", "plan_proposed", "claude-code")

    from superharness.commands.task import status_update

    with pytest.raises(SystemExit) as exc_info:
        status_update(project, "t-other", "plan_approved", "codex-cli")
    assert exc_info.value.code == 1
    assert _status_of(project, "t-other") == "plan_proposed"
