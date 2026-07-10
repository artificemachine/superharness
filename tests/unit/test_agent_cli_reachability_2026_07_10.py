"""Availability-aware fallback: the exhausted-retry recovery path
(_auto_recover_exhausted_failures_sqlite) picked the next fallback agent by
_FALLBACK_ORDER filtered only by quota-limited status — never checking
whether the fallback agent's CLI is actually installed. A task could get
re-routed to an agent whose binary isn't on PATH, guaranteeing another
failure. _agent_cli_reachable() closes that gap; the fallback_agents filter
must also apply it.
"""
from __future__ import annotations

from unittest.mock import patch

from superharness.engine.db import get_connection, init_db
from superharness.commands.inbox_watch import (
    _agent_cli_reachable,
    _auto_recover_exhausted_failures_sqlite,
)


class TestAgentCliReachable:
    def test_true_when_which_finds_binary(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            assert _agent_cli_reachable("claude-code") is True

    def test_false_when_which_returns_none(self):
        with patch("shutil.which", return_value=None):
            assert _agent_cli_reachable("claude-code") is False

    def test_maps_owner_id_to_correct_binary_name(self):
        seen = []

        def fake_which(binary):
            seen.append(binary)
            return "/usr/local/bin/x"

        with patch("shutil.which", side_effect=fake_which):
            _agent_cli_reachable("codex-cli")
            _agent_cli_reachable("gemini-cli")
        assert seen == ["codex", "gemini"]

    def test_unmapped_agent_checks_agent_id_itself(self):
        with patch("shutil.which", return_value="/usr/local/bin/opencode") as m:
            assert _agent_cli_reachable("opencode") is True
            m.assert_called_with("opencode")


NOW = "2026-05-08T00:00:00Z"


def _setup(tmp_path):
    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True)
    conn = get_connection(str(project))
    init_db(conn, str(project))
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at, updated_at) "
        "VALUES ('t1', 't', 'claude-code', 'in_progress', ?, ?)",
        (NOW, NOW),
    )
    conn.commit()
    return str(project), conn


def _seed_inbox(conn, *, recovery_count, max_retries, retry_count, status="failed"):
    conn.execute(
        "INSERT INTO inbox (id, task_id, target_agent, status, retry_count, "
        "max_retries, recovery_count, failed_reason, created_at) "
        "VALUES ('i1', 't1', 'claude-code', ?, ?, ?, ?, "
        "'unknown: unclassified failure (exit code 1)', ?)",
        (status, retry_count, max_retries, recovery_count, NOW),
    )
    conn.commit()


class TestFallbackSkipsUnreachableAgents:
    def test_skips_fallback_agent_with_missing_cli(self, tmp_path):
        """_FALLBACK_ORDER is claude-code, codex-cli, gemini-cli, opencode.
        claude-code is the exhausted current agent (tried). codex-cli's CLI
        is missing — must be skipped in favor of gemini-cli, not picked."""
        project, conn = _setup(tmp_path)
        _seed_inbox(conn, recovery_count=0, max_retries=3, retry_count=3)
        conn.close()

        def fake_which(binary):
            return None if binary == "codex" else f"/usr/local/bin/{binary}"

        with patch("superharness.engine.model_router.is_agent_quota_limited", return_value=False):
            with patch("shutil.which", side_effect=fake_which):
                _auto_recover_exhausted_failures_sqlite(project)

        conn = get_connection(project)
        try:
            target = conn.execute(
                "SELECT target_agent FROM inbox WHERE id='i1'"
            ).fetchone()["target_agent"]
            assert target == "gemini-cli"
        finally:
            conn.close()

    def test_escalates_when_all_fallback_agents_unreachable(self, tmp_path):
        project, conn = _setup(tmp_path)
        _seed_inbox(conn, recovery_count=0, max_retries=3, retry_count=3)
        conn.close()

        with patch("superharness.engine.model_router.is_agent_quota_limited", return_value=False):
            with patch("shutil.which", return_value=None):
                _auto_recover_exhausted_failures_sqlite(project)

        conn = get_connection(project)
        try:
            task_status = conn.execute(
                "SELECT status FROM tasks WHERE id='t1'"
            ).fetchone()["status"]
            assert task_status == "waiting_input"
        finally:
            conn.close()
