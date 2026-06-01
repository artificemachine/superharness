"""Tests for _auto_advance_orphaned_rounds.

Scenario: dispatch sends inbox round items to participating agents. The agents
finish their inbox tasks (status='done') but never call `shux discuss submit`,
so no rows land in `discussion_rounds`. The discussion stays in 'active' forever
and the operator has no signal that the round is effectively complete.

The reconciler detects this state and promotes the discussion to status='consensus'
with a sentinel string so the auto-close path skips it (operator review required).
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db, now_iso
from superharness.engine import discussions_dao
from superharness.commands.inbox_watch import (
    _auto_advance_orphaned_rounds,
    _auto_close_consensus_discussions,
    _ORPHAN_ROUND_GRACE_MINUTES,
    _CONSENSUS_PENDING_REVIEW_PREFIX,
)
from superharness.engine.discussion import _check_all_submitted_and_set_consensus


def _iso_minutes_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_task(conn, task_id: str) -> None:
    """Insert a stub task row to satisfy inbox FK."""
    exists = conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone()
    if exists:
        return
    conn.execute(
        """
        INSERT INTO tasks (id, title, owner, status, acceptance_criteria, test_types,
                           out_of_scope, definition_of_done, version, created_at)
        VALUES (?, ?, ?, 'todo', '[]', '[]', '[]', '[]', 1, ?)
        """,
        (task_id, task_id, "claude-code", now_iso()),
    )


def _seed_inbox_done(conn, *, task_id: str, agent: str, done_minutes_ago: int) -> None:
    """Insert a 'done' inbox row for a discussion round task."""
    _ensure_task(conn, task_id)
    inbox_id = f"ib-{task_id}-{agent}"
    conn.execute(
        """
        INSERT INTO inbox (id, task_id, target_agent, status, priority, retry_count,
                           max_retries, recovery_count, plan_only, created_at, done_at)
        VALUES (?, ?, ?, 'done', 2, 0, 3, 0, 0, ?, ?)
        """,
        (inbox_id, task_id, agent, _iso_minutes_ago(done_minutes_ago + 5),
         _iso_minutes_ago(done_minutes_ago)),
    )


@pytest.fixture
def project_with_db(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    return project


class TestAutoAdvanceOrphanedRounds:
    def test_advances_when_all_inbox_done_no_verdicts_past_grace(self, project_with_db):
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        owners = ["claude-code", "codex-cli", "gemini-cli", "opencode"]
        disc_id = "disc-orphan-1"
        discussions_dao.create(conn, id=disc_id, topic="t", owners=owners, now=now_iso())
        for agent in owners:
            _seed_inbox_done(
                conn,
                task_id=f"{disc_id}/round-1",
                agent=agent,
                done_minutes_ago=_ORPHAN_ROUND_GRACE_MINUTES + 5,
            )
        conn.commit()
        conn.close()

        n = _auto_advance_orphaned_rounds(str(project))
        assert n == 1

        conn = get_connection(str(project))
        try:
            row = discussions_dao.get(conn, disc_id)
            # Zero verdicts submitted → failed_participant, not consensus.
            # Agents completing their inbox task without engaging is a failure,
            # not an orphaned round that needs operator review.
            assert row.status == "failed_participant"
        finally:
            conn.close()

    def test_1_of_3_dispatched_submitted_is_failed_participant(self, project_with_db):
        """3 participants dispatched, only 1 submitted verdict — required=2.
        1/3 < 2 → failed_participant. Prevents the single-participant consensus bug.
        (Fix: BUGREPORT-discussion-consensus-single-participant, root cause #1.)"""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        owners = ["claude-code", "codex-cli", "gemini-cli"]
        disc_id = "disc-1of3"
        discussions_dao.create(conn, id=disc_id, topic="t", owners=owners, now=now_iso())
        for agent in owners:
            _seed_inbox_done(
                conn,
                task_id=f"{disc_id}/round-1",
                agent=agent,
                done_minutes_ago=_ORPHAN_ROUND_GRACE_MINUTES + 5,
            )
        # Only 1 of 3 submitted
        discussions_dao.add_round(
            conn, discussion_id=disc_id, round_number=1,
            agent="claude-code", verdict="agree", now=now_iso(),
        )
        conn.commit()
        conn.close()

        n = _auto_advance_orphaned_rounds(str(project))
        assert n == 1

        conn = get_connection(str(project))
        try:
            row = discussions_dao.get(conn, disc_id)
            assert row.status == "failed_participant", (
                f"1/3 submissions < required=2 must be failed_participant, got {row.status}"
            )
        finally:
            conn.close()

    def test_2_of_3_dispatched_submitted_is_consensus_pending_review(self, project_with_db):
        """3 participants, 2 submitted — required=2. 2/3 >= 2 → consensus (pending review).
        The threshold is met; the single missing verdict is surfaced for operator review."""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        owners = ["claude-code", "codex-cli", "gemini-cli"]
        disc_id = "disc-2of3"
        discussions_dao.create(conn, id=disc_id, topic="t", owners=owners, now=now_iso())
        for agent in owners:
            _seed_inbox_done(
                conn,
                task_id=f"{disc_id}/round-1",
                agent=agent,
                done_minutes_ago=_ORPHAN_ROUND_GRACE_MINUTES + 5,
            )
        # 2 of 3 submitted
        for agent in ("claude-code", "codex-cli"):
            discussions_dao.add_round(
                conn, discussion_id=disc_id, round_number=1,
                agent=agent, verdict="agree", now=now_iso(),
            )
        conn.commit()
        conn.close()

        n = _auto_advance_orphaned_rounds(str(project))
        assert n == 1

        conn = get_connection(str(project))
        try:
            row = discussions_dao.get(conn, disc_id)
            assert row.status == "consensus", (
                f"2/3 submissions >= required=2 must be consensus, got {row.status}"
            )
            assert row.consensus.startswith(_CONSENSUS_PENDING_REVIEW_PREFIX)
            assert "2/3" in row.consensus
        finally:
            conn.close()

    def test_pending_review_consensus_not_auto_closed(self, project_with_db):
        """A consensus row with the pending-review sentinel must not be auto-closed
        by _auto_close_consensus_discussions — operator must close it explicitly."""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        disc_id = "disc-review"
        discussions_dao.create(conn, id=disc_id, topic="t", owners=["a", "b"], now=now_iso())
        # Old enough that the close grace period would normally fire
        old = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "UPDATE discussions SET status='consensus', consensus=?, created_at=? WHERE id=?",
            (
                f"{_CONSENSUS_PENDING_REVIEW_PREFIX} round 1 inbox done, no verdicts",
                old,
                disc_id,
            ),
        )
        conn.commit()
        conn.close()

        n = _auto_close_consensus_discussions(str(project))
        assert n == 0

        conn = get_connection(str(project))
        try:
            row = discussions_dao.get(conn, disc_id)
            assert row.status == "consensus"
            assert row.closed_at is None
        finally:
            conn.close()
