"""Additional GC edge case tests — pushing toward the 35 max."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest
import yaml


def _setup_db(tmp_path: Path) -> sqlite3.Connection:
    harness = tmp_path / ".superharness"
    harness.mkdir()
    db_path = harness / "state.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    from superharness.engine.db import init_db
    init_db(conn)
    conn.commit()
    return conn


def _seed(conn, **kwargs):
    table = kwargs.pop("_table", "tasks")
    cols = ", ".join(kwargs.keys())
    placeholders = ", ".join("?" for _ in kwargs)
    conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})", tuple(kwargs.values()))


# ── GC edge cases (24 tests target) ───────────────────────────────────────────

class TestGCDuplicateEdgeCases:
    """Duplicate inbox edge cases."""

    def test_large_duplicate_batch(self, tmp_path):
        from superharness.commands.inbox_watch import _gc_duplicate_inbox
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="T", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        # Create 5 duplicates
        for i in range(5):
            _seed(conn, _table="inbox", id=f"dup-{i}", task_id="t1", target_agent="claude-code",
                  status="pending", retry_count=0, max_retries=3,
                  created_at=f"2026-01-01T00:0{i}:00Z")
        conn.commit()
        cleaned = _gc_duplicate_inbox(str(tmp_path))
        assert cleaned == 4  # 5 items, 1 kept, 4 canceled
        conn.close()

    def test_multiple_tasks_with_duplicates(self, tmp_path):
        from superharness.commands.inbox_watch import _gc_duplicate_inbox
        conn = _setup_db(tmp_path)
        for tid in ["t1", "t2"]:
            _seed(conn, _table="tasks", id=tid, title=tid, status="in_progress",
                  project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        # Duplicates for two different tasks
        for tid in ["t1", "t2"]:
            _seed(conn, _table="inbox", id=f"{tid}-a", task_id=tid, target_agent="claude-code",
                  status="pending", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z")
            _seed(conn, _table="inbox", id=f"{tid}-b", task_id=tid, target_agent="claude-code",
                  status="pending", retry_count=0, max_retries=3, created_at="2026-01-01T00:01:00Z")
        conn.commit()
        cleaned = _gc_duplicate_inbox(str(tmp_path))
        assert cleaned == 2  # one per task
        conn.close()

    def test_different_agents_not_duplicates(self, tmp_path):
        from superharness.commands.inbox_watch import _gc_duplicate_inbox
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="T", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="a1", task_id="t1", target_agent="claude-code",
              status="pending", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="a2", task_id="t1", target_agent="codex-cli",
              status="pending", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z")
        conn.commit()
        cleaned = _gc_duplicate_inbox(str(tmp_path))
        assert cleaned == 0  # different agents, not duplicates
        conn.close()


class TestGCZombieEdgeCases:
    """Zombie detection edge cases."""

    def test_item_with_null_pid(self, tmp_path):
        from superharness.commands.inbox_watch import _gc_zombie_running
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="T", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="z1", task_id="t1", target_agent="claude-code",
              status="running", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z",
              pid=None)
        conn.commit()
        result = _gc_zombie_running(str(tmp_path))
        assert result >= 0  # shouldn't crash
        conn.close()

    def test_item_with_zero_pid(self, tmp_path):
        from superharness.commands.inbox_watch import _gc_zombie_running
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="T", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="z2", task_id="t1", target_agent="claude-code",
              status="running", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z",
              pid=0)
        conn.commit()
        result = _gc_zombie_running(str(tmp_path))
        assert result >= 0
        conn.close()

    def test_pending_timeout_various_ages(self, tmp_path):
        from superharness.commands.inbox_watch import _gc_zombie_pending
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="T", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        # One old, one recent
        old = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed(conn, _table="inbox", id="old", task_id="t1", target_agent="claude-code",
              status="pending", retry_count=0, max_retries=3, created_at=old)
        _seed(conn, _table="inbox", id="recent", task_id="t1", target_agent="codex-cli",
              status="pending", retry_count=0, max_retries=3, created_at=recent)
        conn.commit()
        result = _gc_zombie_pending(str(tmp_path))
        assert result == 1  # only the old one
        conn.close()


class TestGCDiscussionEdgeCases:
    """Discussion GC edge cases."""

    def test_no_discussions_returns_zero(self, tmp_path):
        from superharness.commands.inbox_watch import _gc_orphaned_discussion_inbox
        conn = _setup_db(tmp_path)
        conn.commit()
        result = _gc_orphaned_discussion_inbox(str(tmp_path))
        assert result == 0
        conn.close()

    def test_active_discussion_not_cleaned(self, tmp_path):
        from superharness.commands.inbox_watch import _gc_orphaned_discussion_inbox
        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('d1', 'test', '[\"claude-code\"]', 'active', '2026-01-01T00:00:00Z')"
        )
        _seed(conn, _table="tasks", id="d1/round-1", title="R1", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="i1", task_id="d1/round-1", target_agent="claude-code",
              status="pending", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z")
        conn.commit()
        result = _gc_orphaned_discussion_inbox(str(tmp_path))
        assert result == 0  # active discussion, no cleanup
        conn.close()

    def test_failed_participant_discussion_cleaned(self, tmp_path):
        from superharness.commands.inbox_watch import _gc_orphaned_discussion_inbox
        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('d-fail', 'test', '[\"claude-code\"]', 'failed_participant', '2026-01-01T00:00:00Z')"
        )
        _seed(conn, _table="tasks", id="d-fail/round-1", title="R1", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="i-fail", task_id="d-fail/round-1", target_agent="claude-code",
              status="pending", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z")
        conn.commit()
        result = _gc_orphaned_discussion_inbox(str(tmp_path))
        assert result == 1  # failed_participant discussion, inbox cleaned
        conn.close()


class TestGCStuckEdgeCases:
    """Stuck task GC edge cases."""

    def test_non_waiting_input_not_touched(self, tmp_path):
        from superharness.commands.inbox_watch import _gc_stuck_waiting_input
        conn = _setup_db(tmp_path)
        old = (datetime.now(timezone.utc) - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed(conn, _table="tasks", id="t-other", title="T", status="in_progress",
              project_path=str(tmp_path), created_at=old, in_progress_at=old)
        conn.commit()
        result = _gc_stuck_waiting_input(str(tmp_path))
        assert result == 0  # not waiting_input
        conn.close()

    def test_recent_waiting_input_untouched(self, tmp_path):
        from superharness.commands.inbox_watch import _gc_stuck_waiting_input
        conn = _setup_db(tmp_path)
        recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed(conn, _table="tasks", id="t-recent", title="T", status="waiting_input",
              project_path=str(tmp_path), created_at=recent, in_progress_at=recent)
        conn.commit()
        result = _gc_stuck_waiting_input(str(tmp_path))
        assert result == 0  # too recent
        conn.close()
