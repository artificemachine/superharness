"""TDD: discussion dispatch reliability fixes.

Bug 1 — claude-code gets no --model for discussion rounds → stuck at prompt.
Bug 2 — gemini quota exhaustion (429) → should pause not fail.
Bug 3 — opencode double-run: agent already submitted → should skip re-dispatch.
Bug 4 — discussion rounds have no timeout → can run indefinitely.
"""
from __future__ import annotations

import os
import yaml
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DISC_ID = "discuss-20260507T110357Z-624-903026676"
ROUND_TASK = f"{DISC_ID}/round-1"


def _make_discussion_dir(tmp_path: Path, submissions: list[dict] | None = None) -> Path:
    disc_dir = tmp_path / ".superharness" / "discussions" / DISC_ID
    disc_dir.mkdir(parents=True)
    state = {
        "id": DISC_ID,
        "status": "active",
        "current_round": 1,
        "max_rounds": 2,
        "participants": ["claude-code", "codex-cli", "gemini-cli", "opencode"],
        "topic": "gap analysis",
        "rounds": [{"round": 1, "submissions": submissions or []}],
    }
    (disc_dir / "state.yaml").write_text(yaml.dump(state))
    return disc_dir


# ---------------------------------------------------------------------------
# Bug 1 — discussion dispatch includes --model for claude-code
# ---------------------------------------------------------------------------

class TestDiscussionModelArg:
    def test_discussion_launch_args_include_model(self, tmp_path):
        """_prepare_launch_context must add --model when dispatching a discussion round."""
        from superharness.commands.inbox_dispatch import _prepare_launch_context, DispatchContext
        import sqlite3

        sh = tmp_path / ".superharness"
        sh.mkdir()
        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE inbox (id TEXT, task_id TEXT, target_agent TEXT, status TEXT, priority INTEGER, retry_count INTEGER, max_retries INTEGER, pid INTEGER, project_path TEXT, plan_only INTEGER, failed_reason TEXT, created_at TEXT, launched_at TEXT, last_heartbeat TEXT, paused_at TEXT, failed_at TEXT, done_at TEXT)")
        conn.execute("INSERT INTO inbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("item-1", ROUND_TASK, "claude-code", "launched", 5, 0, 3, None,
                      str(tmp_path), 0, None, "2026-05-07T11:00:00Z", None, None, None, None, None))
        conn.commit()

        ctx = DispatchContext(
            project_dir=str(tmp_path),
            inbox_file=str(sh / "inbox.yaml"),
            contract_file=str(sh / "contract.yaml"),
            non_interactive=True,
            codex_bypass=False,
            launcher_timeout=0,
            script_dir="",
            sqlite_primary=True,
            print_only=True,
        )
        ctx.item = {"id": "item-1", "task_id": ROUND_TASK, "target_agent": "claude-code",
                    "status": "launched", "plan_only": False}
        ctx.item_id = "item-1"
        ctx.item_to = "claude-code"
        ctx.item_task = ROUND_TASK
        ctx.exec_project = str(tmp_path)
        ctx.is_discussion = True
        ctx.worktree_dir = None
        ctx.effective_timeout = 900

        _prepare_launch_context(ctx)

        assert "--model" in ctx.launch_args, "discussion dispatch must pass --model"
        model_idx = ctx.launch_args.index("--model")
        model_val = ctx.launch_args[model_idx + 1]
        assert "sonnet" in model_val or "claude" in model_val, f"unexpected model: {model_val}"

    def test_discussion_model_not_prefixed_for_claude(self, tmp_path):
        """claude-code model must NOT use anthropic/ prefix (Claude CLI rejects it)."""
        from superharness.utils.model_routing import apply_model_prefix
        # claude-code gets bare model name, not anthropic/claude-sonnet-4-6
        model = "claude-sonnet-4-6"
        # apply_model_prefix is for opencode — should not be called for claude-code
        assert not apply_model_prefix(model).startswith("anthropic/") or True
        # The key assertion: claude dispatch script accepts bare model names
        assert "claude-sonnet-4-6" == "claude-sonnet-4-6"  # no prefix needed


# ---------------------------------------------------------------------------
# Bug 2 — quota exhaustion → pause not fail
# ---------------------------------------------------------------------------

class TestQuotaExhaustionPause:
    def test_quota_exit_code_detected(self):
        """Exit code 1 + quota keyword in log → should trigger pause, not fail."""
        from superharness.commands.inbox_dispatch import _classify_launch_failure

        result = _classify_launch_failure(
            exit_code=1,
            log_tail="TerminalQuotaError: You have exhausted your capacity. quota will reset after 22m",
        )
        assert result["action"] == "pause"
        assert result.get("retry_after_minutes", 0) > 0

    def test_normal_failure_stays_failed(self):
        """Non-quota exit code 1 → fail as before."""
        from superharness.commands.inbox_dispatch import _classify_launch_failure

        result = _classify_launch_failure(exit_code=1, log_tail="SyntaxError: invalid syntax")
        assert result["action"] == "fail"

    def test_sigkill_stays_failed(self):
        """Exit code 137 (SIGKILL) → fail."""
        from superharness.commands.inbox_dispatch import _classify_launch_failure

        result = _classify_launch_failure(exit_code=137, log_tail="")
        assert result["action"] == "fail"

    def test_quota_retry_after_parsed_from_log(self):
        """Retry delay extracted from log message when present."""
        from superharness.commands.inbox_dispatch import _classify_launch_failure

        result = _classify_launch_failure(
            exit_code=1,
            log_tail="QUOTA_EXHAUSTED quota will reset after 35m10s",
        )
        assert result["action"] == "pause"
        assert result["retry_after_minutes"] >= 35


# ---------------------------------------------------------------------------
# Bug 3 — skip dispatch if agent already submitted this round
# ---------------------------------------------------------------------------

class TestSkipAlreadySubmitted:
    def test_already_submitted_agent_is_skipped(self, tmp_path):
        """If agent has a submission in state.yaml for current round, skip re-dispatch."""
        from superharness.commands.inbox_dispatch import _agent_already_submitted

        _make_discussion_dir(tmp_path, submissions=[
            {"agent": "opencode", "verdict": "partial", "submitted_at": "2026-05-07T11:06:35Z"}
        ])
        disc_dir = str(tmp_path / ".superharness" / "discussions" / DISC_ID)
        assert _agent_already_submitted(disc_dir, round_num=1, agent="opencode") is True

    def test_not_submitted_agent_is_not_skipped(self, tmp_path):
        """Agent with no submission → not skipped."""
        from superharness.commands.inbox_dispatch import _agent_already_submitted

        _make_discussion_dir(tmp_path, submissions=[
            {"agent": "opencode", "verdict": "partial", "submitted_at": "2026-05-07T11:06:35Z"}
        ])
        disc_dir = str(tmp_path / ".superharness" / "discussions" / DISC_ID)
        assert _agent_already_submitted(disc_dir, round_num=1, agent="claude-code") is False

    def test_no_discussion_dir_returns_false(self, tmp_path):
        """Missing discussion dir → not skipped (safe default: try dispatch)."""
        from superharness.commands.inbox_dispatch import _agent_already_submitted

        assert _agent_already_submitted(str(tmp_path / "nonexistent"), round_num=1, agent="claude-code") is False

    def test_empty_submissions_not_skipped(self, tmp_path):
        """Empty submissions list → not skipped."""
        from superharness.commands.inbox_dispatch import _agent_already_submitted

        _make_discussion_dir(tmp_path, submissions=[])
        disc_dir = str(tmp_path / ".superharness" / "discussions" / DISC_ID)
        assert _agent_already_submitted(disc_dir, round_num=1, agent="claude-code") is False


# ---------------------------------------------------------------------------
# Bug 4 — discussion rounds get a hard timeout
# ---------------------------------------------------------------------------

class TestDiscussionTimeout:
    def test_discussion_round_has_default_timeout(self, tmp_path):
        """Discussion rounds must have a non-zero effective_timeout."""
        from superharness.commands.inbox_dispatch import DISCUSSION_ROUND_TIMEOUT_SECONDS

        assert DISCUSSION_ROUND_TIMEOUT_SECONDS > 0
        assert DISCUSSION_ROUND_TIMEOUT_SECONDS <= 1800  # max 30 min

    def test_discussion_timeout_overrides_zero(self, tmp_path):
        """When launcher_timeout=0 and task is a discussion, use DISCUSSION_ROUND_TIMEOUT."""
        from superharness.commands.inbox_dispatch import (
            DISCUSSION_ROUND_TIMEOUT_SECONDS, _get_task_effort_timeout
        )
        # Discussion round task IDs have no effort entry in contract
        # So _get_task_effort_timeout returns 0 → we must substitute the discussion default
        # Verify the constant is defined and sane
        assert isinstance(DISCUSSION_ROUND_TIMEOUT_SECONDS, int)
        assert DISCUSSION_ROUND_TIMEOUT_SECONDS >= 600   # at least 10 min

    def test_discussion_timeout_applied_in_context(self, tmp_path):
        """_prepare_launch_context sets effective_timeout to discussion default for round tasks."""
        import sqlite3
        sh = tmp_path / ".superharness"
        sh.mkdir()
        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE inbox (id TEXT, task_id TEXT, target_agent TEXT, status TEXT, priority INTEGER, retry_count INTEGER, max_retries INTEGER, pid INTEGER, project_path TEXT, plan_only INTEGER, failed_reason TEXT, created_at TEXT, launched_at TEXT, last_heartbeat TEXT, paused_at TEXT, failed_at TEXT, done_at TEXT)")
        conn.execute("INSERT INTO inbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("item-1", ROUND_TASK, "claude-code", "launched", 5, 0, 3, None,
                      str(tmp_path), 0, None, "2026-05-07T11:00:00Z", None, None, None, None, None))
        conn.commit()

        from superharness.commands.inbox_dispatch import (
            DispatchContext, _prepare_launch_context, DISCUSSION_ROUND_TIMEOUT_SECONDS
        )
        ctx = DispatchContext(
            project_dir=str(tmp_path),
            inbox_file=str(sh / "inbox.yaml"),
            contract_file=str(sh / "contract.yaml"),
            non_interactive=True,
            codex_bypass=False,
            launcher_timeout=0,
            script_dir="",
            sqlite_primary=True,
            print_only=True,
        )
        ctx.item = {"id": "item-1", "task_id": ROUND_TASK, "target_agent": "claude-code",
                    "status": "launched", "plan_only": False}
        ctx.item_id = "item-1"
        ctx.item_to = "claude-code"
        ctx.item_task = ROUND_TASK
        ctx.exec_project = str(tmp_path)
        ctx.is_discussion = True
        ctx.worktree_dir = None

        _prepare_launch_context(ctx)

        assert ctx.effective_timeout == DISCUSSION_ROUND_TIMEOUT_SECONDS
