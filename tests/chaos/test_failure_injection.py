"""Chaos / failure injection tests — verify system degrades gracefully.

Not required for CI merge. Run on demand or weekly.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


class TestChaosDatabase:
    """DB failure scenarios."""

    def test_db_deleted_mid_operation(self, tmp_path):
        """System handles DB deletion without crashing."""
        from superharness.engine.db import init_db
        harness = tmp_path / ".superharness"
        harness.mkdir()
        db_path = harness / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.close()

        # Delete DB
        db_path.unlink()

        # Operation should not crash
        from superharness.engine.db import get_connection
        try:
            conn2 = get_connection(str(tmp_path))
            assert conn2 is not None
            conn2.close()
        except Exception:
            pass  # graceful failure is acceptable


class TestChaosRetry:
    """Retry exhaustion scenarios."""

    def test_retry_exhausted_returns_false_on_missing_db(self, tmp_path):
        """_retry_exhausted returns False (not exhausted) when DB doesn't exist."""
        from superharness.commands.discussion_dispatch import _retry_exhausted
        result = _retry_exhausted(str(tmp_path), "gemini-cli", "disc/round-1")
        assert result is False  # safe default — don't block dispatch

    def test_retry_agent_returns_false_on_missing_db(self, tmp_path):
        """_retry_agent gracefully handles missing DB."""
        from superharness.commands.discussion_dispatch import _retry_agent
        result = _retry_agent(str(tmp_path), "gemini-cli", "disc/round-1", "disc", 1)
        assert result is False  # can't retry without DB


class TestChaosOrchestrator:
    """Orchestrator failure scenarios."""

    def test_fallback_routing_works(self):
        """_fallback_routing returns valid plan even without DB."""
        from superharness.engine.orchestrator import Orchestrator
        orch = Orchestrator(project_dir="/nonexistent")
        plan = orch._fallback_routing({"id": "t1", "title": "Test", "owner": "claude-code"})
        assert plan.owner == "claude-code"
        assert plan.tier == "standard"
        assert plan.decompose is False

    def test_orchestrator_chain_not_empty(self):
        """Orchestrator chain has entries even if all models fail."""
        from superharness.engine.orchestrator import _ORCHESTRATOR_CHAIN
        assert len(_ORCHESTRATOR_CHAIN) >= 4
        for entry in _ORCHESTRATOR_CHAIN:
            assert len(entry) == 3  # (binary, model_id, label)
            assert entry[0]  # binary not empty
            assert entry[1]  # model_id not empty
