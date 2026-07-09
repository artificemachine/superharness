"""Regression test for 2026-07-09: `abstain`/`consensus` verdicts spawned
spurious action tasks on a successful consensus close.

`_create_consensus_task` is only ever called after `compute_consensus`
returns True (discussion.py `_check_all_submitted_and_set_consensus`), so
every participant verdict reaching it is in
`_CONSENSUS_VERDICTS = {agree, consensus, abstain}`.

But the actionable-item filter tested `verdict != "agree"`, so `abstain`
(agent explicitly declined to take a position) and `consensus` (agent
agreed) were both treated as action items. A discussion closing on
`abstain + abstain` reached consensus and then generated
`[abstain] <topic>` implementation tasks in `plan_proposed` for agents who
had declined to weigh in.

Fix: filter on membership in `_CONSENSUS_VERDICTS`, not equality with
"agree". `disagree`/`partial` remain actionable (reachable here only from
non-participant submissions or direct calls).
"""
from __future__ import annotations

import os

import pytest

from superharness.engine import discussions_dao
from superharness.engine.db import get_connection, init_db
from superharness.engine.discussion import _CONSENSUS_VERDICTS, _create_consensus_task


NOW = "2026-07-09T00:00:00Z"


def _setup(tmp_path, disc_id: str, owners: list[str]):
    project = str(tmp_path / "proj")
    os.makedirs(os.path.join(project, ".superharness"), exist_ok=True)
    conn = get_connection(project)
    init_db(conn, project_dir=project)
    conn.execute(
        "INSERT INTO discussions (id, topic, status, owners, created_at) VALUES (?,?,?,?,?)",
        (disc_id, "Refactor auth module", "open", '["' + '","'.join(owners) + '"]', NOW),
    )
    conn.commit()
    return project, conn


def _disc_row(disc_id: str, owners: list[str]):
    return discussions_dao.DiscussionRow(
        id=disc_id, topic="Refactor auth module", status="open", owners=owners,
        consensus=None, created_at=NOW, closed_at=None, task_id=None,
    )


def _submit(conn, disc_id: str, agent: str, verdict: str, round_: int = 1):
    conn.execute(
        "INSERT INTO discussion_rounds (discussion_id, round_number, agent, verdict, created_at) "
        "VALUES (?,?,?,?,?)",
        (disc_id, round_, agent, verdict, NOW),
    )
    conn.commit()


def _action_task_ids(conn) -> list[str]:
    rows = conn.execute("SELECT id FROM tasks WHERE id LIKE 'action-%'").fetchall()
    return [r["id"] for r in rows]


@pytest.mark.parametrize("verdict", sorted(_CONSENSUS_VERDICTS))
def test_consensus_verdicts_create_no_action_tasks(tmp_path, verdict):
    """No verdict that permits consensus may generate an action task."""
    disc_id = f"discuss-abstain-{verdict}-20260709T000000Z"
    owners = ["claude-code", "codex-cli"]
    project, conn = _setup(tmp_path, disc_id, owners)

    for agent in owners:
        _submit(conn, disc_id, agent, verdict)

    _create_consensus_task(conn, _disc_row(disc_id, owners), 1, set(owners), project_dir=project)

    assert _action_task_ids(conn) == [], (
        f"verdict '{verdict}' permits consensus but generated action tasks: "
        f"{_action_task_ids(conn)}"
    )
    conn.close()


@pytest.mark.parametrize("verdict", ["disagree", "partial"])
def test_blocking_verdicts_still_create_action_tasks(tmp_path, verdict):
    """disagree/partial remain actionable — this path is reachable via direct
    calls and non-participant submissions, and existing callers depend on it."""
    disc_id = f"discuss-blocking-{verdict}-20260709T000000Z"
    owners = ["claude-code"]
    project, conn = _setup(tmp_path, disc_id, owners)

    _submit(conn, disc_id, "claude-code", verdict)

    _create_consensus_task(conn, _disc_row(disc_id, owners), 1, set(owners), project_dir=project)

    assert _action_task_ids(conn), (
        f"verdict '{verdict}' blocks consensus and must still yield an action task"
    )
    conn.close()
