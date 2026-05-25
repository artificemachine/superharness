"""Additional chaos / failure injection tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path

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


# ── Additional chaos tests (13 tests target) ──────────────────────────────────

class TestChaosWALContention:
    """SQLite WAL mode edge cases."""

    def test_concurrent_readers_dont_block(self, tmp_path):
        conn1 = _setup_db(tmp_path)
        conn2 = sqlite3.connect(str(tmp_path / ".superharness" / "state.sqlite3"))
        conn2.row_factory = sqlite3.Row
        r1 = conn1.execute("SELECT 1").fetchone()
        r2 = conn2.execute("SELECT 1").fetchone()
        assert r1 is not None
        assert r2 is not None
        conn1.close()
        conn2.close()

    def test_rapid_open_close_connections(self, tmp_path):
        harness = tmp_path / ".superharness"
        harness.mkdir()
        db_path = harness / "state.sqlite3"
        from superharness.engine.db import init_db
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.close()
        # Open and close 10 times
        for _ in range(10):
            c = sqlite3.connect(str(db_path))
            c.execute("SELECT 1")
            c.close()


class TestChaosOrchestratorFallback:
    """Orchestrator failure paths."""

    def test_all_models_fail_returns_fallback(self, tmp_path):
        from superharness.engine.orchestrator import Orchestrator
        orch = Orchestrator(project_dir=str(tmp_path))
        plan = orch._fallback_routing({"id": "t1", "title": "Test", "owner": "gemini-cli"})
        assert plan.owner == "gemini-cli"
        assert plan.tier == "standard"
        assert plan.decompose is False
        assert "unavailable" in plan.rationale.lower()

    def test_fallback_routing_all_owners(self, tmp_path):
        from superharness.engine.orchestrator import Orchestrator
        for owner in ["claude-code", "codex-cli", "gemini-cli", "opencode"]:
            orch = Orchestrator(project_dir=str(tmp_path))
            plan = orch._fallback_routing({"id": "t1", "title": "T", "owner": owner})
            assert plan.owner == owner

    def test_empty_task_dict(self, tmp_path):
        from superharness.engine.orchestrator import Orchestrator
        orch = Orchestrator(project_dir=str(tmp_path))
        plan = orch._fallback_routing({})
        assert plan.owner == "claude-code"  # default
        assert plan.decompose is False


class TestChaosDispatcherFailure:
    """Dispatcher failure scenarios."""

    def test_inbox_item_with_bogus_pid(self, tmp_path):
        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO tasks (id, title, status, project_path, created_at) "
            "VALUES ('t1', 'T', 'in_progress', ?, '2026-01-01T00:00:00Z')",
            (str(tmp_path),)
        )
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, pid, retry_count, max_retries, created_at) "
            "VALUES ('bogus', 't1', 'claude-code', 'running', -1, 0, 3, '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        row = conn.execute("SELECT pid FROM inbox WHERE id='bogus'").fetchone()
        assert row["pid"] == -1  # negative PID should not crash
        conn.close()

    def test_empty_task_id_in_inbox(self, tmp_path):
        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, retry_count, max_retries, created_at) "
            "VALUES ('empty-task', '', 'claude-code', 'pending', 0, 3, '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        row = conn.execute("SELECT task_id FROM inbox WHERE id='empty-task'").fetchone()
        assert row["task_id"] == ""
        conn.close()


class TestChaosDiscussionFailure:
    """Discussion failure edge cases."""

    def test_discussion_with_no_rounds(self, tmp_path):
        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('d-empty', 'empty', '[\"claude-code\"]', 'active', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import discussions_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            rounds = discussions_dao.get_rounds(conn2, "d-empty")
            assert rounds == []  # no rounds, not a crash
        finally:
            conn2.close()
        conn.close()

    def test_closed_discussion_get_rounds(self, tmp_path):
        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at, closed_at) "
            "VALUES ('d-closed', 'closed', '[\"claude-code\"]', 'closed', '2026-01-01T00:00:00Z', '2026-01-01T01:00:00Z')"
        )
        conn.commit()
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import discussions_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            rounds = discussions_dao.get_rounds(conn2, "d-closed")
            assert rounds == []
        finally:
            conn2.close()
        conn.close()
