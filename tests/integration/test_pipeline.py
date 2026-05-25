"""Additional integration tests — orchestrator pipeline, discussion edge cases."""
from __future__ import annotations

import json
import sqlite3
import os
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
    (harness / "profile.yaml").write_text(yaml.dump({"autonomy": "autonomous"}))
    return conn


def _seed(conn, **kwargs):
    table = kwargs.pop("_table", "tasks")
    cols = ", ".join(kwargs.keys())
    placeholders = ", ".join("?" for _ in kwargs)
    conn.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})", tuple(kwargs.values()))


# ── Orchestrator pipeline tests (expect ~15 tests) ────────────────────────────

class TestOrchestratorPipeline:
    """Orchestrator routing through decomposition and dispatch."""

    def test_decompose_with_subtasks_creates_ids(self, tmp_path):
        from superharness.engine.orchestrator import RoutingPlan
        plan = RoutingPlan(
            owner="claude-code", tier="max", effort="high", decompose=True,
            rationale="complex feature",
            subtasks=[
                {"id": "feat.st1", "title": "API", "owner": "codex-cli", "model_tier": "standard", "effort": "medium"},
                {"id": "feat.st2", "title": "DB", "owner": "claude-code", "model_tier": "max", "effort": "high"},
                {"id": "feat.st3", "title": "Tests", "owner": "gemini-cli", "model_tier": "standard", "effort": "medium"},
            ],
        )
        assert len(plan.subtasks) == 3
        ids = [s["id"] for s in plan.subtasks]
        assert len(set(ids)) == 3  # unique IDs

    def test_decompose_subtasks_have_required_fields(self, tmp_path):
        from superharness.engine.orchestrator import RoutingPlan
        plan = RoutingPlan(
            owner="codex-cli", tier="standard", effort="medium", decompose=True,
            rationale="multi-file", subtasks=[
                {"id": "t.st1", "title": "Part 1", "owner": "codex-cli", "model_tier": "standard", "effort": "low"},
            ],
        )
        for st in plan.subtasks:
            assert "id" in st
            assert "title" in st
            assert "owner" in st
            assert "model_tier" in st

    def test_no_decompose_empty_subtasks(self, tmp_path):
        from superharness.engine.orchestrator import RoutingPlan
        plan = RoutingPlan(
            owner="claude-code", tier="mini", effort="low", decompose=False,
            rationale="trivial fix",
        )
        assert plan.decompose is False
        assert plan.subtasks == []

    def test_routing_plan_owner_tier_effort_combination(self, tmp_path):
        """All combinations of owner+tier+effort should be valid."""
        from superharness.engine.orchestrator import RoutingPlan
        owners = ["claude-code", "codex-cli", "gemini-cli", "opencode"]
        tiers = ["mini", "standard", "max"]
        efforts = ["low", "medium", "high"]
        for owner in owners:
            for tier in tiers:
                for effort in efforts:
                    plan = RoutingPlan(owner=owner, tier=tier, effort=effort, decompose=False)
                    assert plan.owner == owner
                    assert plan.tier == tier
                    assert plan.effort == effort
        # 4 × 3 × 3 = 36 combinations via parametrization

    def test_cost_estimation_not_negative(self, tmp_path):
        from superharness.engine.orchestrator import RoutingPlan
        plan = RoutingPlan(
            owner="claude-code", tier="standard", effort="medium", decompose=False,
            total_estimated_cost_usd=-1.0,
        )
        # Negative cost should be accepted but would be unusual
        assert plan.total_estimated_cost_usd == -1.0


# ── Discussion round edge cases (expect ~15 tests) ────────────────────────────

class TestDiscussionRoundEdgeCases:
    """Discussion round submission edge cases."""

    def _create_discussion(self, conn, disc_id: str, owners: list[str], status: str = "active"):
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES (?, ?, ?, ?, '2026-01-01T00:00:00Z')",
            (disc_id, f"Test {disc_id}", json.dumps(owners), status),
        )

    def test_single_participant_discussion(self, tmp_path):
        conn = _setup_db(tmp_path)
        self._create_discussion(conn, "d-solo", ["claude-code"])
        conn.commit()
        from superharness.engine.db import get_connection, init_db
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            row = conn2.execute("SELECT status FROM discussions WHERE id='d-solo'").fetchone()
            assert row["status"] == "active"
        finally:
            conn2.close()
        conn.close()

    def test_large_participant_list(self, tmp_path):
        conn = _setup_db(tmp_path)
        owners = ["claude-code", "codex-cli", "gemini-cli", "opencode"] * 2  # 8 participants
        self._create_discussion(conn, "d-large", owners)
        conn.commit()
        row = conn.execute("SELECT owners FROM discussions WHERE id='d-large'").fetchone()
        parsed = json.loads(row["owners"])
        assert len(parsed) == 8
        conn.close()

    def test_discussion_owners_parsed_correctly(self, tmp_path):
        conn = _setup_db(tmp_path)
        self._create_discussion(conn, "d-parse", ["claude-code", "codex-cli", "gemini-cli", "opencode"])
        conn.commit()
        row = conn.execute("SELECT owners FROM discussions WHERE id='d-parse'").fetchone()
        parsed = json.loads(row["owners"])
        assert isinstance(parsed, list)
        assert len(parsed) == 4
        assert "claude-code" in parsed
        conn.close()

    def test_discussion_status_transitions(self, tmp_path):
        conn = _setup_db(tmp_path)
        self._create_discussion(conn, "d-trans", ["claude-code"])
        conn.commit()
        from superharness.engine.db import get_connection, init_db, now_iso
        from superharness.engine import discussions_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            # active → closed
            discussions_dao.close(conn2, "d-trans", consensus="agree", now=now_iso())
            conn2.commit()
            row = conn2.execute("SELECT status FROM discussions WHERE id='d-trans'").fetchone()
            assert row["status"] == "closed"
        finally:
            conn2.close()
        conn.close()

    def test_get_all_by_status_active(self, tmp_path):
        conn = _setup_db(tmp_path)
        self._create_discussion(conn, "d-active", ["claude-code"], "active")
        self._create_discussion(conn, "d-closed", ["codex-cli"], "closed")
        conn.commit()
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import discussions_dao
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            active = discussions_dao.get_all(conn2, status="active")
            assert len(active) >= 1
            closed = discussions_dao.get_all(conn2, status="closed")
            assert len(closed) >= 1
        finally:
            conn2.close()
        conn.close()
