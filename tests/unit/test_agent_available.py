"""Tests for _agent_available — agent availability gate."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


def _recent_ts(hours_ago: float = 1.0) -> str:
    """ISO timestamp within the 24-hour recency window."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


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


class TestAgentAvailable:
    """Tests for _agent_available function."""

    def test_agent_with_binary_is_available(self, tmp_path):
        """Agent whose binary exists on PATH → available."""
        from superharness.commands.discussion_dispatch import _agent_available
        available, reason = _agent_available("claude-code", str(tmp_path))
        # claude binary should exist on most systems with superharness
        assert available or "not installed" in reason

    def test_rate_limited_agent_is_unavailable(self, tmp_path):
        """Agent with recent rate-limit failure → unavailable."""
        from superharness.commands.discussion_dispatch import _agent_available
        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, failed_reason, retry_count, max_retries, created_at) "
            f"VALUES ('rl-1', 't1', 'gemini-cli', 'failed', 'rate limit exceeded', 3, 3, '{_recent_ts()}')"
        )
        conn.commit()

        available, reason = _agent_available("gemini-cli", str(tmp_path))
        assert not available
        assert "rate limit" in reason.lower()
        conn.close()

    def test_quota_exhausted_agent_is_unavailable(self, tmp_path):
        """Agent with quota exhaustion → unavailable."""
        from superharness.commands.discussion_dispatch import _agent_available
        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, failed_reason, retry_count, max_retries, created_at) "
            f"VALUES ('q-1', 't1', 'codex-cli', 'failed', 'quota exceeded for gpt-5.5', 3, 3, '{_recent_ts()}')"
        )
        conn.commit()

        available, reason = _agent_available("codex-cli", str(tmp_path))
        assert not available
        assert "quota" in reason.lower()
        conn.close()

    def test_permanent_block_agent_is_unavailable(self, tmp_path):
        """Agent with permanent block → unavailable."""
        from superharness.commands.discussion_dispatch import _agent_available
        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, failed_reason, retry_count, max_retries, created_at) "
            f"VALUES ('pb-1', 't1', 'opencode', 'failed', 'permanent block: lifecycle gate', 3, 3, '{_recent_ts()}')"
        )
        conn.commit()

        available, reason = _agent_available("opencode", str(tmp_path))
        assert not available
        assert "permanent" in reason.lower()
        conn.close()

    def test_agent_without_recent_failure_is_available(self, tmp_path):
        """Agent with no recent failures → available."""
        from superharness.commands.discussion_dispatch import _agent_available
        conn = _setup_db(tmp_path)
        conn.commit()

        available, reason = _agent_available("claude-code", str(tmp_path))
        # No failed rows = no rate limit evidence
        assert available or "not installed" in reason
        conn.close()

    def test_unrelated_failure_does_not_block(self, tmp_path):
        """Agent with a non-rate-limit failure → still available."""
        from superharness.commands.discussion_dispatch import _agent_available
        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO inbox (id, task_id, target_agent, status, failed_reason, retry_count, max_retries, created_at) "
            "VALUES ('other', 't1', 'gemini-cli', 'failed', 'PREFLIGHT FAIL: GEMINI.md missing', 1, 3, '2026-01-01T00:00:00Z')"
        )
        conn.commit()

        available, reason = _agent_available("gemini-cli", str(tmp_path))
        # Preflight failure is not rate-limit — agent is still available
        assert available
        conn.close()
