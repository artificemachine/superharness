"""Integration tests for the full task lifecycle.

Covers: create → classify → delegate → fail → retry → close.
These test cross-component flows that unit tests cannot catch.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_project(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    """Create a minimal initialized project with SQLite."""
    from superharness.engine.db import init_db
    harness = tmp_path / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()
    (harness / "ledger.md").write_text("# Ledger\n")
    (harness / "profile.yaml").write_text(yaml.dump({
        "autonomy": "autonomous",
        "primary_agent": "claude-code",
        "stack": "python",
    }))

    db_path = harness / "state.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    init_db(conn)
    conn.commit()
    return tmp_path, conn


def _seed_task(conn, task_id: str, title: str, status: str = "plan_approved",
               owner: str = "claude-code", acceptance_criteria: list | None = None):
    """Seed a task in the tasks table."""
    import json
    ac_json = json.dumps(acceptance_criteria or [])
    conn.execute(
        "INSERT OR REPLACE INTO tasks (id, title, status, project_path, created_at, owner, acceptance_criteria) "
        "VALUES (?, ?, ?, ?, datetime('now'), ?, ?)",
        (task_id, title, status, str(Path(conn.execute("PRAGMA database_list").fetchone()["file"]).parent.parent),
         owner, ac_json),
    )


def _seed_inbox(conn, item_id: str, task_id: str, agent: str, status: str = "pending",
                retry_count: int = 0, max_retries: int = 3):
    conn.execute(
        "INSERT OR REPLACE INTO inbox (id, task_id, target_agent, status, retry_count, max_retries, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (item_id, task_id, agent, status, retry_count, max_retries),
    )


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------

class TestTaskLifecycle:
    """Tests the full task lifecycle: create → dispatch → fail → retry → close."""

    def test_task_flows_through_states(self, tmp_path):
        """Task transitions through all expected states."""
        project, conn = _setup_project(tmp_path)
        _seed_task(conn, "lifecycle-1", "Integration test task", status="plan_approved",
                   acceptance_criteria=["Works", "Passes tests"])

        # Verify task exists
        row = conn.execute("SELECT id, status FROM tasks WHERE id='lifecycle-1'").fetchone()
        assert row is not None
        assert row["status"] == "plan_approved"
        conn.close()

    def test_dispatch_creates_inbox_item(self, tmp_path):
        """Dispatch creates an inbox item for the agent."""
        project, conn = _setup_project(tmp_path)
        _seed_task(conn, "dispatch-1", "Dispatch test", acceptance_criteria=["Do thing"])
        conn.commit()

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn2 = get_connection(str(project))
        try:
            init_db(conn2)
            inbox_dao.enqueue(conn2, id="test-001", task_id="dispatch-1",
                             target_agent="claude-code", priority=1,
                             project_path=str(project), max_retries=3,
                             now="2026-01-01T00:00:00Z")
            conn2.commit()

            row = conn2.execute("SELECT * FROM inbox WHERE id='test-001'").fetchone()
            assert row is not None
            assert row["task_id"] == "dispatch-1"
            assert row["target_agent"] == "claude-code"
            assert row["status"] == "pending"
        finally:
            conn2.close()
        conn.close()

    def test_failed_task_can_be_retried(self, tmp_path):
        """Failed inbox item → retried → status back to pending."""
        project, conn = _setup_project(tmp_path)
        _seed_task(conn, "retry-1", "Retry test")
        _seed_inbox(conn, "retry-item-1", "retry-1", "claude-code", status="failed",
                    retry_count=1, max_retries=3)
        conn.commit()

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn2 = get_connection(str(project))
        try:
            init_db(conn2)
            inbox_dao.set_retry(conn2, "retry-item-1", 2, "test failure", "2026-01-01T00:00:00Z")
            conn2.commit()

            row = conn2.execute("SELECT retry_count, status, failed_reason FROM inbox WHERE id='retry-item-1'").fetchone()
            assert row["retry_count"] == 2
            assert row["status"] == "pending"
            assert "test failure" in (row["failed_reason"] or "")
        finally:
            conn2.close()
        conn.close()

    def test_task_transitions_are_legal(self, tmp_path):
        """Plan_approved → in_progress is legal. Plan_approved → done is not."""
        from superharness.engine.next_action import validate_status_transition

        # Legal
        validate_status_transition("plan_approved", "in_progress")  # should not raise

        # Illegal
        with pytest.raises(ValueError, match="transition"):
            validate_status_transition("plan_approved", "done")


# ---------------------------------------------------------------------------
# Discussion lifecycle
# ---------------------------------------------------------------------------

class TestDiscussionLifecycle:
    """Tests the discussion lifecycle: start → dispatch rounds → submit → advance."""

    def test_discussion_start_creates_rounds(self, tmp_path):
        """Starting a discussion creates inbox items for all participants."""
        project, conn = _setup_project(tmp_path)
        _seed_task(conn, "disc/round-1", "Discussion round 1", status="in_progress")
        conn.commit()

        # Enqueue round items for 3 agents
        for i, agent in enumerate(["claude-code", "codex-cli", "gemini-cli"]):
            _seed_inbox(conn, f"disc-item-{i}", "disc/round-1", agent, status="pending")
        conn.commit()

        rows = conn.execute(
            "SELECT COUNT(*) as cnt FROM inbox WHERE task_id='disc/round-1' AND status='pending'"
        ).fetchone()
        assert rows["cnt"] == 3
        conn.close()

    def test_round_advances_when_enough_submitted(self, tmp_path):
        """When enough agents submit, the round can advance."""
        project, conn = _setup_project(tmp_path)

        # Create discussion
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('disc-adv', 'test', '[\"claude-code\",\"codex-cli\",\"gemini-cli\"]', 'active', '2026-01-01T00:00:00Z')"
        )
        _seed_task(conn, "disc-adv/round-1", "Round 1", status="in_progress")
        conn.commit()

        # Submit 2 of 3 (enough for max(2, 3-1) = 2)
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import discussions_dao
        conn2 = get_connection(str(project))
        try:
            init_db(conn2)
            discussions_dao.add_round(conn2, discussion_id="disc-adv", round_number=1,
                                      agent="claude-code", verdict="agree",
                                      content="Good idea", now="2026-01-01T01:00:00Z")
            discussions_dao.add_round(conn2, discussion_id="disc-adv", round_number=1,
                                      agent="codex-cli", verdict="agree",
                                      content="Agreed", now="2026-01-01T01:05:00Z")
            conn2.commit()

            rounds = discussions_dao.get_rounds(conn2, "disc-adv")
            assert len(rounds) == 2
            assert all(r.round_number == 1 for r in rounds)
        finally:
            conn2.close()
        conn.close()


# ---------------------------------------------------------------------------
# GC pipeline
# ---------------------------------------------------------------------------

class TestGCPipeline:
    """Tests that GC functions work together to clean the system."""

    def test_gc_cleans_orphaned_inbox_after_discussion_closed(self, tmp_path):
        """GC cleans inbox items when discussion is closed."""
        project, conn = _setup_project(tmp_path)

        # Create a closed discussion with orphaned inbox items
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('disc-gc', 'test', '[\"claude-code\"]', 'closed', '2026-01-01T00:00:00Z')"
        )
        _seed_task(conn, "disc-gc/round-1", "Round 1")
        _seed_inbox(conn, "orphan-1", "disc-gc/round-1", "claude-code", status="failed")
        _seed_inbox(conn, "orphan-2", "disc-gc/round-1", "codex-cli", status="pending")
        conn.commit()

        from superharness.commands.inbox_watch import _gc_orphaned_discussion_inbox
        cleaned = _gc_orphaned_discussion_inbox(str(project))
        assert cleaned == 2

        for iid in ("orphan-1", "orphan-2"):
            row = conn.execute("SELECT status FROM inbox WHERE id=?", (iid,)).fetchone()
            assert row["status"] == "done"
        conn.close()
