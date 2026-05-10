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
            assert row.status == "consensus"
            assert row.consensus.startswith(_CONSENSUS_PENDING_REVIEW_PREFIX)
            assert "round 1" in row.consensus.lower()
        finally:
            conn.close()

    def test_skips_within_grace_period(self, project_with_db):
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        owners = ["claude-code", "codex-cli"]
        disc_id = "disc-fresh"
        discussions_dao.create(conn, id=disc_id, topic="t", owners=owners, now=now_iso())
        for agent in owners:
            _seed_inbox_done(
                conn,
                task_id=f"{disc_id}/round-1",
                agent=agent,
                done_minutes_ago=1,
            )
        conn.commit()
        conn.close()

        n = _auto_advance_orphaned_rounds(str(project))
        assert n == 0

        conn = get_connection(str(project))
        try:
            row = discussions_dao.get(conn, disc_id)
            assert row.status == "active"
        finally:
            conn.close()

    def test_skips_when_inbox_not_all_done(self, project_with_db):
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        owners = ["claude-code", "codex-cli"]
        disc_id = "disc-partial"
        discussions_dao.create(conn, id=disc_id, topic="t", owners=owners, now=now_iso())
        # Only one of two participants has finished inbox
        _seed_inbox_done(
            conn,
            task_id=f"{disc_id}/round-1",
            agent="claude-code",
            done_minutes_ago=_ORPHAN_ROUND_GRACE_MINUTES + 5,
        )
        _ensure_task(conn, f"{disc_id}/round-1")
        conn.execute(
            """
            INSERT INTO inbox (id, task_id, target_agent, status, priority, retry_count,
                               max_retries, recovery_count, plan_only, created_at)
            VALUES (?, ?, ?, 'running', 2, 0, 3, 0, 0, ?)
            """,
            (f"ib-{disc_id}-codex", f"{disc_id}/round-1", "codex-cli", _iso_minutes_ago(60)),
        )
        conn.commit()
        conn.close()

        n = _auto_advance_orphaned_rounds(str(project))
        assert n == 0

    def test_skips_when_full_verdicts_already_recorded(self, project_with_db):
        """When the normal submit path has populated discussion_rounds for all
        owners, the verdict-driven flow handles it — reconciler should not interfere."""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        owners = ["claude-code", "codex-cli"]
        disc_id = "disc-verdicts"
        discussions_dao.create(conn, id=disc_id, topic="t", owners=owners, now=now_iso())
        for agent in owners:
            _seed_inbox_done(
                conn,
                task_id=f"{disc_id}/round-1",
                agent=agent,
                done_minutes_ago=_ORPHAN_ROUND_GRACE_MINUTES + 5,
            )
            discussions_dao.add_round(
                conn,
                discussion_id=disc_id,
                round_number=1,
                agent=agent,
                verdict="agree",
                now=now_iso(),
            )
        conn.commit()
        conn.close()

        n = _auto_advance_orphaned_rounds(str(project))
        assert n == 0

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
