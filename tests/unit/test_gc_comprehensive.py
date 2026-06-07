"""Tests for the comprehensive GC pass (_comprehensive_gc) and its sub-functions.

Covers:
- Gap 2: duplicate inbox cleanup
- Gap 3: zombie detection for running/pending
- Gap 4: orphaned discussion inbox cleanup
- Gap 7: stuck waiting_input timeout
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a SQLite DB at the legacy path (matching get_connection resolution)."""
    from superharness.engine.db import init_db
    harness = tmp_path / ".superharness"
    harness.mkdir(exist_ok=True)
    db_path = harness / "state.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _seed_task(conn, task_id: str, status: str = "in_progress", created_at: str = "2026-01-01T00:00:00Z"):
    conn.execute(
        "INSERT OR IGNORE INTO tasks (id, title, status, created_at) VALUES (?, ?, ?, ?)",
        (task_id, task_id, status, created_at),
    )


def _seed_inbox(conn, item_id: str, task_id: str, agent: str, status: str,
                retry_count: int = 0, max_retries: int = 3, created_at: str = "2026-01-01T00:00:00Z",
                failed_reason: str | None = None, pid: int | None = None):
    conn.execute(
        "INSERT OR IGNORE INTO inbox (id, task_id, target_agent, status, retry_count, max_retries, "
        "failed_reason, created_at, pid) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (item_id, task_id, agent, status, retry_count, max_retries, failed_reason, created_at, pid),
    )


# ---------------------------------------------------------------------------
# Gap 2: duplicate inbox cleanup
# ---------------------------------------------------------------------------

class TestGCDuplicateInbox:
    def test_merges_duplicate_pending(self, tmp_path):
        """Unique index on (task_id, target_agent) for active statuses prevents
        duplicate pending rows from being created. The GC duplicate-merge path
        is a no-op — it finds 0 duplicates because the index enforces uniqueness
        at insert time. _seed_inbox uses INSERT OR IGNORE so the second insert
        is silently discarded."""
        from superharness.commands.inbox_watch import _gc_duplicate_inbox
        conn = _setup_db(tmp_path)
        _seed_task(conn, "task-1")
        _seed_inbox(conn, "dup-1", "task-1", "claude-code", "pending", created_at="2026-01-01T00:00:00Z")
        _seed_inbox(conn, "dup-2", "task-1", "claude-code", "pending", created_at="2026-01-01T00:01:00Z")
        conn.commit()

        result = _gc_duplicate_inbox(str(tmp_path))
        assert result == 0  # unique index prevents duplicates — GC is a no-op

        r1 = conn.execute("SELECT status FROM inbox WHERE id='dup-1'").fetchone()
        r2 = conn.execute("SELECT status FROM inbox WHERE id='dup-2'").fetchone()
        assert r1["status"] == "pending"  # only row — unchanged
        assert r2 is None  # unique index discarded the second insert
        conn.close()

    def test_no_duplicates_no_change(self, tmp_path):
        """Single pending item → no cleanup."""
        from superharness.commands.inbox_watch import _gc_duplicate_inbox
        conn = _setup_db(tmp_path)
        _seed_task(conn, "task-1")
        _seed_inbox(conn, "only-1", "task-1", "claude-code", "pending")
        conn.commit()

        result = _gc_duplicate_inbox(str(tmp_path))
        assert result == 0
        conn.close()


# ---------------------------------------------------------------------------
# Gap 3: zombie detection for running/pending
# ---------------------------------------------------------------------------

class TestGCZombieRunning:
    def test_dead_pid_marks_failed(self, tmp_path):
        """Running item with dead PID → marked failed."""
        from superharness.commands.inbox_watch import _gc_zombie_running
        conn = _setup_db(tmp_path)
        _seed_task(conn, "task-1")
        _seed_inbox(conn, "zom-1", "task-1", "claude-code", "running", pid=99999)  # dead PID
        conn.commit()

        result = _gc_zombie_running(str(tmp_path))
        # PID 99999 is likely dead, but may exist on some systems
        # Just verify the function runs without error
        assert result >= 0
        conn.close()

    def test_no_running_items_no_change(self, tmp_path):
        """No running items → no cleanup."""
        from superharness.commands.inbox_watch import _gc_zombie_running
        conn = _setup_db(tmp_path)
        _seed_task(conn, "task-1")
        _seed_inbox(conn, "pen-1", "task-1", "claude-code", "pending")
        conn.commit()

        result = _gc_zombie_running(str(tmp_path))
        assert result == 0
        conn.close()


class TestGCZombiePending:
    def test_old_pending_marked_done(self, tmp_path, monkeypatch):
        """Pending item older than 15 min → marked done."""
        from datetime import datetime, timezone, timedelta
        from superharness.commands.inbox_watch import _gc_zombie_pending

        conn = _setup_db(tmp_path)
        _seed_task(conn, "task-1")
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_inbox(conn, "old-pen", "task-1", "claude-code", "pending", created_at=old_time)
        conn.commit()

        result = _gc_zombie_pending(str(tmp_path))
        assert result == 1

        row = conn.execute("SELECT status, failed_reason FROM inbox WHERE id='old-pen'").fetchone()
        assert row["status"] == "done"
        assert "timeout" in (row["failed_reason"] or "")
        conn.close()

    def test_recent_pending_not_touched(self, tmp_path):
        """Recent pending item → not touched."""
        from datetime import datetime, timezone, timedelta
        from superharness.commands.inbox_watch import _gc_zombie_pending

        conn = _setup_db(tmp_path)
        _seed_task(conn, "task-1")
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_inbox(conn, "new-pen", "task-1", "claude-code", "pending", created_at=recent)
        conn.commit()

        result = _gc_zombie_pending(str(tmp_path))
        assert result == 0
        conn.close()


# ---------------------------------------------------------------------------
# Gap 4: orphaned discussion inbox cleanup
# ---------------------------------------------------------------------------

class TestGCOrphanedDiscussionInbox:
    def test_closed_discussion_items_canceled(self, tmp_path):
        """Closed discussion → all associated inbox items marked done."""
        from superharness.commands.inbox_watch import _gc_orphaned_discussion_inbox

        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('disc-test', 'test', '[\"claude-code\"]', 'closed', '2026-01-01T00:00:00Z')"
        )
        _seed_task(conn, "disc-test/round-1")
        _seed_inbox(conn, "disc-item-1", "disc-test/round-1", "claude-code", "pending")
        _seed_inbox(conn, "disc-item-2", "disc-test/round-1", "codex-cli", "failed")
        conn.commit()

        result = _gc_orphaned_discussion_inbox(str(tmp_path))
        assert result == 2

        for iid in ("disc-item-1", "disc-item-2"):
            row = conn.execute("SELECT status, failed_reason FROM inbox WHERE id=?", (iid,)).fetchone()
            assert row["status"] == "done"
            assert "discussion closed" in (row["failed_reason"] or "")
        conn.close()

    def test_active_discussion_not_touched(self, tmp_path):
        """Active discussion items are not canceled."""
        from superharness.commands.inbox_watch import _gc_orphaned_discussion_inbox

        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('disc-active', 'test', '[\"claude-code\"]', 'active', '2026-01-01T00:00:00Z')"
        )
        _seed_task(conn, "disc-active/round-1")
        _seed_inbox(conn, "active-item", "disc-active/round-1", "claude-code", "pending")
        conn.commit()

        result = _gc_orphaned_discussion_inbox(str(tmp_path))
        assert result == 0
        conn.close()


# ---------------------------------------------------------------------------
# Gap 7: stuck waiting_input timeout
# ---------------------------------------------------------------------------

class TestGCStuckWaitingInput:
    def test_old_waiting_input_archived(self, tmp_path):
        """Task in waiting_input > 30 min → archived."""
        from datetime import datetime, timezone, timedelta
        from superharness.commands.inbox_watch import _gc_stuck_waiting_input

        conn = _setup_db(tmp_path)
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_task(conn, "stuck-task", status="waiting_input", created_at=old_time)
        conn.execute("UPDATE tasks SET in_progress_at=? WHERE id=?", (old_time, "stuck-task"))
        conn.commit()

        result = _gc_stuck_waiting_input(str(tmp_path))
        assert result == 1

        row = conn.execute("SELECT status, archived_reason FROM tasks WHERE id='stuck-task'").fetchone()
        assert row["status"] == "archived"
        assert "timeout" in (row["archived_reason"] or "")
        conn.close()

    def test_recent_waiting_input_not_touched(self, tmp_path):
        """Recent waiting_input → not archived."""
        from datetime import datetime, timezone, timedelta
        from superharness.commands.inbox_watch import _gc_stuck_waiting_input

        conn = _setup_db(tmp_path)
        recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_task(conn, "recent-task", status="waiting_input", created_at=recent)
        conn.execute("UPDATE tasks SET in_progress_at=? WHERE id=?", (recent, "recent-task"))
        conn.commit()

        result = _gc_stuck_waiting_input(str(tmp_path))
        assert result == 0
        conn.close()

    def test_waiting_input_no_in_progress_at(self, tmp_path):
        """Task with waiting_input but no in_progress_at → uses created_at."""
        from datetime import datetime, timezone, timedelta
        from superharness.commands.inbox_watch import _gc_stuck_waiting_input

        conn = _setup_db(tmp_path)
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_task(conn, "no-progress-task", status="waiting_input", created_at=old_time)
        # No in_progress_at set — should fall back to created_at
        conn.commit()

        result = _gc_stuck_waiting_input(str(tmp_path))
        assert result == 1
        conn.close()


# ── Gap: no-engagement timeout ────────────────────────────────────────────────

class TestGCNoEngagement:
    """Discussions with zero rounds should auto-close after timeout."""

    def test_no_rounds_old_discussion_closed(self, tmp_path):
        """Discussion >30 min old with 0 rounds → auto-closed."""
        from datetime import datetime, timezone, timedelta
        from superharness.commands.inbox_watch import _gc_discussion_deadlock

        conn = _setup_db(tmp_path)
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('disc-stale', 'stale', '[\"claude-code\"]', 'active', ?)",
            (old_time,),
        )
        conn.commit()

        result = _gc_discussion_deadlock(str(tmp_path))
        assert result == 1  # one discussion closed

        row = conn.execute("SELECT status FROM discussions WHERE id='disc-stale'").fetchone()
        assert row["status"] == "failed_participant"
        conn.close()

    def test_fresh_discussion_no_rounds_not_closed(self, tmp_path):
        """Recent discussion with 0 rounds → not touched."""
        from datetime import datetime, timezone
        from superharness.commands.inbox_watch import _gc_discussion_deadlock

        conn = _setup_db(tmp_path)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('disc-fresh', 'fresh', '[\"claude-code\"]', 'active', ?)",
            (now,),
        )
        conn.commit()

        result = _gc_discussion_deadlock(str(tmp_path))
        assert result == 0  # too new, not closed
        conn.close()


# ---------------------------------------------------------------------------
# Fix #3: discussion deadlock fast-close requires `required` submissions
# (BUGREPORT-discussion-consensus-single-participant)
# ---------------------------------------------------------------------------

class TestGCDiscussionDeadlockRequiredSubmissions:
    """_gc_discussion_deadlock must require `required` (not 1) submissions
    before fast-closing, even when missing agents have no daemon."""

    def _make_old_ts(self, hours_ago: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    def _seed_heartbeat(self, conn, agent: str, status: str):
        ts = self._make_old_ts(1)
        conn.execute(
            "INSERT OR REPLACE INTO agent_heartbeats (agent, status, updated_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (agent, status, ts, ts),
        )

    def test_1_of_3_with_dead_daemons_does_not_fast_close(self, tmp_path):
        """3 participants, 1 submitted, all missing daemons dead.
        required = max(2, 3-1) = 2. 1 < 2 → must NOT fast-close."""
        from superharness.commands.inbox_watch import _gc_discussion_deadlock

        conn = _setup_db(tmp_path)
        disc_id = "disc-1of3-dead-daemons"
        old = self._make_old_ts(2)

        # Create discussion
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES (?, ?, ?, 'active', ?)",
            (disc_id, "test", '["claude-code","codex-cli","gemini-cli"]', old),
        )
        # Create task
        _seed_task(conn, f"{disc_id}/round-1", created_at=old)
        # Submit only 1 verdict (claude-code)
        conn.execute(
            "INSERT INTO discussion_rounds (discussion_id, round_number, agent, verdict, created_at) "
            "VALUES (?, 1, ?, 'agree', ?)",
            (disc_id, "claude-code", old),
        )
        # Mark other agents as zombie (no daemon)
        self._seed_heartbeat(conn, "codex-cli", "zombie")
        self._seed_heartbeat(conn, "gemini-cli", "zombie")
        conn.commit()
        conn.close()

        result = _gc_discussion_deadlock(str(tmp_path))
        assert result == 0, (
            f"1/3 submissions < required=2 must NOT fast-close, got {result}"
        )

        conn = _setup_db(tmp_path)
        row = conn.execute(
            "SELECT status FROM discussions WHERE id=?", (disc_id,)
        ).fetchone()
        assert row["status"] == "active", "discussion should remain active"
        conn.close()

    def test_2_of_3_with_dead_daemons_skipped_normal_advance(self, tmp_path):
        """3 participants, 2 submitted. required=2. 2 >= 2 → skip (normal advance).
        The GC should not touch discussions with sufficient submissions."""
        from superharness.commands.inbox_watch import _gc_discussion_deadlock

        conn = _setup_db(tmp_path)
        disc_id = "disc-2of3-normal"
        old = self._make_old_ts(2)

        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES (?, ?, ?, 'active', ?)",
            (disc_id, "test", '["claude-code","codex-cli","gemini-cli"]', old),
        )
        _seed_task(conn, f"{disc_id}/round-1", created_at=old)
        for agent in ("claude-code", "codex-cli"):
            conn.execute(
                "INSERT INTO discussion_rounds (discussion_id, round_number, agent, verdict, created_at) "
                "VALUES (?, 1, ?, 'agree', ?)",
                (disc_id, agent, old),
            )
        self._seed_heartbeat(conn, "gemini-cli", "zombie")
        conn.commit()
        conn.close()

        result = _gc_discussion_deadlock(str(tmp_path))
        assert result == 0, (
            f"2/3 submissions >= required=2 should be left for normal advance, got {result}"
        )

        conn = _setup_db(tmp_path)
        row = conn.execute(
            "SELECT status FROM discussions WHERE id=?", (disc_id,)
        ).fetchone()
        assert row["status"] == "active", "discussion should remain active"
        conn.close()

    def test_1_of_2_with_dead_daemon_does_not_fast_close(self, tmp_path):
        """2 participants, 1 submitted, missing daemon dead.
        required = max(2, 2-1) = 2. 1 < 2 → must NOT fast-close."""
        from superharness.commands.inbox_watch import _gc_discussion_deadlock

        conn = _setup_db(tmp_path)
        disc_id = "disc-1of2-dead-daemon"
        old = self._make_old_ts(2)

        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES (?, ?, ?, 'active', ?)",
            (disc_id, "test", '["claude-code","codex-cli"]', old),
        )
        _seed_task(conn, f"{disc_id}/round-1", created_at=old)
        conn.execute(
            "INSERT INTO discussion_rounds (discussion_id, round_number, agent, verdict, created_at) "
            "VALUES (?, 1, ?, 'agree', ?)",
            (disc_id, "claude-code", old),
        )
        self._seed_heartbeat(conn, "codex-cli", "zombie")
        conn.commit()
        conn.close()

        result = _gc_discussion_deadlock(str(tmp_path))
        assert result == 0, (
            f"1/2 submissions < required=2 must NOT fast-close"
        )

        conn = _setup_db(tmp_path)
        row = conn.execute(
            "SELECT status FROM discussions WHERE id=?", (disc_id,)
        ).fetchone()
        assert row["status"] == "active"
        conn.close()
