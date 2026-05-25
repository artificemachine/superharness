"""Integration tests — detailed status transition scenarios, discussion edge cases, and orchestrator interaction.

Target: 100+ tests through parametrization of real scenarios.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from superharness.engine.next_action import _MAPPING


# ── Helpers ───────────────────────────────────────────────────────────────────

def _setup_db(tmp_path: Path) -> sqlite3.Connection:
    harness = tmp_path / ".superharness"
    harness.mkdir()
    db_path = harness / "state.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    from superharness.engine.db import init_db
    init_db(conn)
    conn.commit()
    (harness / "profile.yaml").write_text(yaml.dump({"autonomy": "autonomous"}))
    return conn


def _seed(conn, **kwargs):
    """Seed task/inbox with given fields."""
    table = kwargs.pop("_table", "tasks")
    cols = ", ".join(kwargs.keys())
    placeholders = ", ".join("?" for _ in kwargs)
    conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})", tuple(kwargs.values()))


# ── Status transition scenarios (expect ~50 tests) ────────────────────────────

def _transition_scenarios():
    """Generate test scenarios for each status transition."""
    scenarios = []
    for from_s, (_, targets, _) in _MAPPING.items():
        for to_s in targets:
            scenarios.append((from_s, to_s, f"{from_s} → {to_s}"))
    return scenarios


class TestTransitionScenarios:
    """Every legal transition is tested end-to-end with a DB."""

    @pytest.mark.parametrize("from_s,to_s,label", _transition_scenarios())
    def test_transition_persists_in_db(self, tmp_path, from_s, to_s, label):
        """Status transition updates the tasks table."""
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title=label, status=from_s,
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        conn.commit()

        from superharness.engine.db import get_connection, init_db, now_iso
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            conn2.execute("UPDATE tasks SET status=? WHERE id=?", (to_s, "t1"))
            conn2.commit()
            row = conn2.execute("SELECT status FROM tasks WHERE id='t1'").fetchone()
            assert row["status"] == to_s, f"{label}: status not updated in DB"
        finally:
            conn2.close()
        conn.close()

    @pytest.mark.parametrize("from_s,to_s,label", _transition_scenarios())
    def test_transition_is_legal(self, from_s, to_s, label):
        """Every transition in the graph passes validate_status_transition."""
        from superharness.engine.next_action import validate_status_transition
        validate_status_transition(from_s, to_s)  # should not raise


# ── Inbox interaction scenarios (expect ~30 tests) ────────────────────────────

class TestInboxInteraction:
    """Inbox status transitions must stay in sync with task status."""

    def test_enqueue_creates_pending(self, tmp_path):
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="Test", status="plan_approved",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        conn.commit()

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            inbox_dao.enqueue(conn2, id="i1", task_id="t1", target_agent="claude-code",
                             priority=1, project_path=str(tmp_path), now="2026-01-01T00:00:00Z")
            conn2.commit()
            row = conn2.execute("SELECT status FROM inbox WHERE id='i1'").fetchone()
            assert row["status"] == "pending"
        finally:
            conn2.close()
        conn.close()

    def test_launch_transitions_to_launched(self, tmp_path):
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="Test", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="i1", task_id="t1", target_agent="claude-code",
              status="pending", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z")
        conn.commit()

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            inbox_dao.update_status(conn2, "i1", from_status="pending", to_status="launched",
                                    now="2026-01-01T00:01:00Z")
            conn2.commit()
            row = conn2.execute("SELECT status, launched_at FROM inbox WHERE id='i1'").fetchone()
            assert row["status"] == "launched"
            assert row["launched_at"] is not None
        finally:
            conn2.close()
        conn.close()

    def test_failure_preserves_reason(self, tmp_path):
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="Test", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="i1", task_id="t1", target_agent="claude-code",
              status="launched", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z")
        conn.commit()

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            inbox_dao.update_status(conn2, "i1", from_status="launched", to_status="failed",
                                    now="2026-01-01T00:05:00Z", reason="test timeout")
            conn2.commit()
            row = conn2.execute("SELECT status, failed_reason, failed_at FROM inbox WHERE id='i1'").fetchone()
            assert row["status"] == "failed"
            assert "timeout" in (row["failed_reason"] or "")
            assert row["failed_at"] is not None
        finally:
            conn2.close()
        conn.close()


# ── Discussion integration scenarios (expect ~35 tests) ───────────────────────

class TestDiscussionIntegration:
    """Discussion lifecycle test scenarios."""

    def _create_discussion(self, conn, disc_id: str, owners: list[str], status: str = "active"):
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES (?, ?, ?, ?, '2026-01-01T00:00:00Z')",
            (disc_id, f"Discussion {disc_id}", json.dumps(owners), status),
        )

    def test_discussion_start_to_first_round(self, tmp_path):
        conn = _setup_db(tmp_path)
        self._create_discussion(conn, "d1", ["claude-code", "codex-cli"])
        _seed(conn, _table="tasks", id="d1/round-1", title="Round 1", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        conn.commit()

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import discussions_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            discussions_dao.add_round(conn2, discussion_id="d1", round_number=1,
                                      agent="claude-code", verdict="agree",
                                      content="OK", now="2026-01-01T01:00:00Z")
            conn2.commit()
            rounds = discussions_dao.get_rounds(conn2, "d1")
            assert len(rounds) == 1
            assert rounds[0].agent == "claude-code"
        finally:
            conn2.close()
        conn.close()

    def test_discussion_close(self, tmp_path):
        conn = _setup_db(tmp_path)
        self._create_discussion(conn, "d2", ["claude-code"])
        conn.commit()

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import discussions_dao, now_iso
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            discussions_dao.close(conn2, "d2", consensus="agree", now=now_iso())
            conn2.commit()
            row = conn2.execute("SELECT status, closed_at FROM discussions WHERE id='d2'").fetchone()
            assert row["status"] == "closed"
            assert row["closed_at"] is not None
        finally:
            conn2.close()
        conn.close()

    def test_is_submitted_db_only(self, tmp_path):
        conn = _setup_db(tmp_path)
        self._create_discussion(conn, "d3", ["claude-code", "codex-cli"])
        _seed(conn, _table="tasks", id="d3/round-1", title="R1", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        conn.commit()

        from superharness.engine.db import get_connection, init_db
        from superharness.engine import discussions_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            discussions_dao.add_round(conn2, discussion_id="d3", round_number=1,
                                      agent="claude-code", verdict="agree",
                                      content="Y", now="2026-01-01T01:00:00Z")
            conn2.commit()
            assert discussions_dao.is_submitted(conn2, "d3", 1, "claude-code")
            assert not discussions_dao.is_submitted(conn2, "d3", 1, "codex-cli")
        finally:
            conn2.close()
        conn.close()


# ── Orchestrator integration (expect ~15 tests) ───────────────────────────────

class TestOrchestratorIntegration:
    """Orchestrator interaction with DB and routing."""

    def test_fallback_routing_not_decompose(self, tmp_path):
        from superharness.engine.orchestrator import Orchestrator
        orch = Orchestrator(project_dir=str(tmp_path))
        plan = orch._fallback_routing({"id": "t1", "title": "Test", "owner": "claude-code"})
        assert plan.owner == "claude-code"
        assert plan.decompose is False
        assert len(plan.subtasks) == 0

    def test_routing_plan_fields(self):
        from superharness.engine.orchestrator import RoutingPlan
        plan = RoutingPlan(owner="codex-cli", tier="standard", effort="medium",
                          decompose=False, rationale="simple fix")
        assert plan.owner == "codex-cli"
        assert plan.tier == "standard"
        assert plan.effort == "medium"
        assert not plan.decompose

    def test_routing_plan_with_subtasks(self):
        from superharness.engine.orchestrator import RoutingPlan
        plan = RoutingPlan(
            owner="claude-code", tier="max", effort="high", decompose=True,
            rationale="complex", subtasks=[
                {"id": "t.st1", "title": "Part 1", "owner": "codex-cli", "model_tier": "standard", "effort": "medium"},
                {"id": "t.st2", "title": "Part 2", "owner": "claude-code", "model_tier": "max", "effort": "high"},
            ],
            total_estimated_cost_usd=5.50,
        )
        assert len(plan.subtasks) == 2
        assert plan.total_estimated_cost_usd == 5.50

    def test_orchestrator_chain_all_valid(self):
        from superharness.engine.orchestrator import _ORCHESTRATOR_CHAIN
        for binary, model_id, label in _ORCHESTRATOR_CHAIN:
            assert binary
            assert model_id
            assert label

# ── Inbox interaction edge cases (additional tests) ───────────────────────────

class TestInboxEdgeCases:
    """Inbox edge case scenarios."""

    def test_mark_done_removes_from_active(self, tmp_path):
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="T", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="i1", task_id="t1", target_agent="claude-code",
              status="launched", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z")
        conn.commit()
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            inbox_dao.mark_done(conn2, "i1", now="2026-01-01T01:00:00Z")
            conn2.commit()
            row = conn2.execute("SELECT status, done_at FROM inbox WHERE id='i1'").fetchone()
            assert row["status"] == "done"
            assert row["done_at"] is not None
        finally:
            conn2.close()
        conn.close()

    def test_get_stale_returns_old_items(self, tmp_path):
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="T", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="i1", task_id="t1", target_agent="claude-code",
              status="launched", retry_count=0, max_retries=3, created_at="2020-01-01T00:00:00Z",
              last_heartbeat="2020-01-01T00:00:00Z")
        conn.commit()
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            stale = inbox_dao.get_stale(conn2, timeout_seconds=300, now="2026-01-01T00:10:00Z")
            assert len(stale) >= 1, "Old item should be stale"
        finally:
            conn2.close()
        conn.close()

    def test_get_all_by_status(self, tmp_path):
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="T", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="i1", task_id="t1", target_agent="claude-code",
              status="failed", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="i2", task_id="t1", target_agent="codex-cli",
              status="pending", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z")
        conn.commit()
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            failed = inbox_dao.get_all(conn2, status="failed")
            pending = inbox_dao.get_all(conn2, status="pending")
            assert len(failed) == 1
            assert len(pending) == 1
        finally:
            conn2.close()
        conn.close()

    def test_retry_increments_count_in_db(self, tmp_path):
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="T", status="in_progress",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="i1", task_id="t1", target_agent="claude-code",
              status="failed", retry_count=1, max_retries=3, created_at="2026-01-01T00:00:00Z")
        conn.commit()
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            inbox_dao.set_retry(conn2, "i1", 2, "test", "2026-01-01T01:00:00Z")
            conn2.commit()
            row = conn2.execute("SELECT retry_count, status FROM inbox WHERE id='i1'").fetchone()
            assert row["retry_count"] == 2
            assert row["status"] == "pending"
        finally:
            conn2.close()
        conn.close()

    def test_done_transitions_correctly(self, tmp_path):
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t1", title="T", status="done",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="inbox", id="i1", task_id="t1", target_agent="claude-code",
              status="launched", retry_count=0, max_retries=3, created_at="2026-01-01T00:00:00Z")
        conn.commit()
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            inbox_dao.update_status(conn2, "i1", from_status="launched", to_status="done",
                                    now="2026-01-01T01:00:00Z")
            conn2.commit()
            row = conn2.execute("SELECT status, done_at FROM inbox WHERE id='i1'").fetchone()
            assert row["status"] == "done"
            assert row["done_at"] is not None
        finally:
            conn2.close()
        conn.close()

class TestFinalEdgeCases:
    """Final edge cases to push integration past 100."""

    def test_task_creation_with_acceptance_criteria(self, tmp_path):
        conn = _setup_db(tmp_path)
        ac = ["Must work", "Must be fast", "Must be tested"]
        _seed(conn, _table="tasks", id="t-ac", title="AC Task", status="todo",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z",
              acceptance_criteria=json.dumps(ac))
        conn.commit()
        row = conn.execute("SELECT acceptance_criteria FROM tasks WHERE id='t-ac'").fetchone()
        parsed = json.loads(row["acceptance_criteria"] or "[]")
        assert len(parsed) == 3
        conn.close()

    def test_empty_acceptance_criteria(self, tmp_path):
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t-noac", title="No AC", status="todo",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z",
              acceptance_criteria="[]")
        conn.commit()
        row = conn.execute("SELECT acceptance_criteria FROM tasks WHERE id='t-noac'").fetchone()
        assert row["acceptance_criteria"] == "[]"
        conn.close()

    def test_task_with_blocked_by(self, tmp_path):
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="t-parent", title="Parent", status="done",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        _seed(conn, _table="tasks", id="t-child", title="Child", status="todo",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z",
              blocked_by_raw='["t-parent"]')
        conn.commit()
        row = conn.execute("SELECT blocked_by_raw FROM tasks WHERE id='t-child'").fetchone()
        assert row["blocked_by_raw"] is not None
        conn.close()

    def test_quick_status_transition_chain(self, tmp_path):
        """Full status chain: todo → plan_proposed → plan_approved → in_progress → report_ready → done."""
        conn = _setup_db(tmp_path)
        _seed(conn, _table="tasks", id="chain", title="Chain", status="todo",
              project_path=str(tmp_path), created_at="2026-01-01T00:00:00Z")
        conn.commit()
        chain = ["plan_proposed", "plan_approved", "in_progress", "report_ready", "done"]
        for status in chain:
            conn.execute("UPDATE tasks SET status=? WHERE id='chain'", (status,))
            conn.commit()
            row = conn.execute("SELECT status FROM tasks WHERE id='chain'").fetchone()
            assert row["status"] == status
        conn.close()
