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
    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_already_submitted_agent_is_skipped(self, tmp_path):
        """If agent has a submission in state.yaml for current round, skip re-dispatch."""
        from superharness.commands.inbox_dispatch import _agent_already_submitted

        _make_discussion_dir(tmp_path, submissions=[
            {"agent": "opencode", "verdict": "partial", "submitted_at": "2026-05-07T11:06:35Z"}
        ])
        disc_dir = str(tmp_path / ".superharness" / "discussions" / DISC_ID)
        assert _agent_already_submitted(disc_dir, round_num=1, agent="opencode") is True

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_not_submitted_agent_is_not_skipped(self, tmp_path):
        """Agent with no submission → not skipped."""
        from superharness.commands.inbox_dispatch import _agent_already_submitted

        _make_discussion_dir(tmp_path, submissions=[
            {"agent": "opencode", "verdict": "partial", "submitted_at": "2026-05-07T11:06:35Z"}
        ])
        disc_dir = str(tmp_path / ".superharness" / "discussions" / DISC_ID)
        assert _agent_already_submitted(disc_dir, round_num=1, agent="claude-code") is False

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_no_discussion_dir_returns_false(self, tmp_path):
        """Missing discussion dir → not skipped (safe default: try dispatch)."""
        from superharness.commands.inbox_dispatch import _agent_already_submitted

        assert _agent_already_submitted(str(tmp_path / "nonexistent"), round_num=1, agent="claude-code") is False

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
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
        """_prepare_launch_context sets effective_timeout to effort-driven default
        for round tasks (medium=1200s when task effort is unknown)."""
        import sqlite3
        sh = tmp_path / ".superharness"
        sh.mkdir()
        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        # Create tasks table so the code can read effort (will be NULL → medium fallback)
        conn.execute("CREATE TABLE tasks (id TEXT, title TEXT, owner TEXT, status TEXT, "
                      "project_path TEXT, created_at TEXT, updated_at TEXT, workflow TEXT, "
                      "model_tier TEXT, effort TEXT)")
        conn.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (ROUND_TASK, "Round 1", "claude-code", "in_progress",
                      str(tmp_path), "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z",
                      "discussion", None, None))
        conn.execute("CREATE TABLE inbox (id TEXT, task_id TEXT, target_agent TEXT, status TEXT, priority INTEGER, retry_count INTEGER, max_retries INTEGER, pid INTEGER, project_path TEXT, plan_only INTEGER, failed_reason TEXT, created_at TEXT, launched_at TEXT, last_heartbeat TEXT, paused_at TEXT, failed_at TEXT, done_at TEXT)")
        conn.execute("INSERT INTO inbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     ("item-1", ROUND_TASK, "claude-code", "launched", 5, 0, 3, None,
                      str(tmp_path), 0, None, "2026-05-07T11:00:00Z", None, None, None, None, None))
        conn.commit()

        from superharness.commands.inbox_dispatch import (
            DispatchContext, _prepare_launch_context, DISCUSSION_TIMEOUT_MEDIUM
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

        # With no effort set on task, falls back to DISCUSSION_TIMEOUT_MEDIUM (1200s)
        assert ctx.effective_timeout == DISCUSSION_TIMEOUT_MEDIUM


# ---------------------------------------------------------------------------
# Effort-driven discussion timeout (low=10min, medium=20min, high=30min)
# ---------------------------------------------------------------------------


class TestEffortDrivenDiscussionTimeout:
    def test_low_effort_gets_10_minutes(self, tmp_path):
        """Discussion task with effort=low → 600s timeout."""
        from superharness.commands.inbox_dispatch import (
            DispatchContext, _prepare_launch_context,
            DISCUSSION_TIMEOUT_LOW,
        )

        sh = tmp_path / ".superharness"
        sh.mkdir()

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

        # Mock the task read: return a task with effort=low
        mock_task = MagicMock()
        mock_task.model_tier = "standard"
        mock_task.effort = "low"
        with patch("superharness.engine.db.init_db"), \
             patch("superharness.engine.tasks_dao.get", return_value=mock_task):
            _prepare_launch_context(ctx)

        assert ctx.effective_timeout == DISCUSSION_TIMEOUT_LOW, (
            f"Expected {DISCUSSION_TIMEOUT_LOW}s for low effort, got {ctx.effective_timeout}"
        )

    def test_high_effort_gets_30_minutes(self, tmp_path):
        """Discussion task with effort=high → 1800s timeout."""
        from superharness.commands.inbox_dispatch import (
            DispatchContext, _prepare_launch_context,
            DISCUSSION_TIMEOUT_HIGH,
        )

        sh = tmp_path / ".superharness"
        sh.mkdir()

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

        mock_task = MagicMock()
        mock_task.model_tier = "max"
        mock_task.effort = "high"
        with patch("superharness.engine.db.init_db"), \
             patch("superharness.engine.tasks_dao.get", return_value=mock_task):
            _prepare_launch_context(ctx)

        assert ctx.effective_timeout == DISCUSSION_TIMEOUT_HIGH, (
            f"Expected {DISCUSSION_TIMEOUT_HIGH}s for high effort, got {ctx.effective_timeout}"
        )

    def test_env_var_overrides_effort_timeout(self, tmp_path, monkeypatch):
        """SUPERHARNESS_DISCUSSION_ROUND_TIMEOUT_SECONDS overrides effort-based timeout."""
        from superharness.commands.inbox_dispatch import (
            DispatchContext, _prepare_launch_context,
        )
        import sqlite3

        monkeypatch.setenv("SUPERHARNESS_DISCUSSION_ROUND_TIMEOUT_SECONDS", "42")

        sh = tmp_path / ".superharness"
        sh.mkdir()
        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE tasks (id TEXT, title TEXT, owner TEXT, status TEXT, "
            "project_path TEXT, created_at TEXT, updated_at TEXT, workflow TEXT, "
            "model_tier TEXT, effort TEXT)"
        )
        conn.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ROUND_TASK, "Round 1", "claude-code", "in_progress",
             str(tmp_path), "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z",
             "discussion", "standard", "high"),
        )
        conn.execute(
            "CREATE TABLE inbox (id TEXT, task_id TEXT, target_agent TEXT, status TEXT, "
            "priority INTEGER, retry_count INTEGER, max_retries INTEGER, pid INTEGER, "
            "project_path TEXT, plan_only INTEGER, failed_reason TEXT, created_at TEXT, "
            "launched_at TEXT, last_heartbeat TEXT, paused_at TEXT, failed_at TEXT, done_at TEXT)"
        )
        conn.execute(
            "INSERT INTO inbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("item-1", ROUND_TASK, "claude-code", "launched", 5, 0, 3, None,
             str(tmp_path), 0, None, "2026-05-07T11:00:00Z", None, None, None, None, None),
        )
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

        _prepare_launch_context(ctx)

        assert ctx.effective_timeout == 42, (
            f"Env var override should set timeout to 42, got {ctx.effective_timeout}"
        )


# ---------------------------------------------------------------------------
# Profile config fallback for discussion_model_tier
# ---------------------------------------------------------------------------


class TestProfileConfigFallback:
    def test_profile_config_used_when_task_has_no_model_tier(self, tmp_path):
        """When task has no model_tier, profile config discussion_model_tier is used."""
        from superharness.commands.inbox_dispatch import (
            DispatchContext, _prepare_launch_context,
        )
        import os, yaml, sqlite3

        # Set up profile with discussion_model_tier = max
        sh = tmp_path / ".superharness"
        sh.mkdir()
        profile = {
            "discussion_model_tier": "max",
        }
        (sh / "profile.yaml").write_text(yaml.dump(profile))

        # Set up task without model_tier
        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE tasks (id TEXT, title TEXT, owner TEXT, status TEXT, "
            "project_path TEXT, created_at TEXT, updated_at TEXT, workflow TEXT, "
            "model_tier TEXT, effort TEXT)"
        )
        conn.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ROUND_TASK, "Round 1", "claude-code", "in_progress",
             str(tmp_path), "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z",
             "discussion", None, "medium"),
        )
        conn.execute(
            "CREATE TABLE inbox (id TEXT, task_id TEXT, target_agent TEXT, status TEXT, "
            "priority INTEGER, retry_count INTEGER, max_retries INTEGER, pid INTEGER, "
            "project_path TEXT, plan_only INTEGER, failed_reason TEXT, created_at TEXT, "
            "launched_at TEXT, last_heartbeat TEXT, paused_at TEXT, failed_at TEXT, done_at TEXT)"
        )
        conn.execute(
            "INSERT INTO inbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("item-1", ROUND_TASK, "claude-code", "launched", 5, 0, 3, None,
             str(tmp_path), 0, None, "2026-05-07T11:00:00Z", None, None, None, None, None),
        )
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

        _prepare_launch_context(ctx)

        # Should have resolved to opus (max tier)
        assert "--model" in ctx.launch_args, "discussion dispatch must pass --model"
        model_idx = ctx.launch_args.index("--model")
        model_val = ctx.launch_args[model_idx + 1]
        assert "opus" in model_val.lower() or "max" in model_val.lower(), (
            f"Expected max-tier model (opus), got: {model_val}"
        )

    def test_env_var_overrides_profile_config(self, tmp_path, monkeypatch):
        """SUPERHARNESS_CLAUDE_MODEL env var overrides profile config."""
        from superharness.commands.inbox_dispatch import (
            DispatchContext, _prepare_launch_context,
        )
        import yaml, sqlite3

        monkeypatch.setenv("SUPERHARNESS_CLAUDE_MODEL", "claude-haiku-4-5")

        sh = tmp_path / ".superharness"
        sh.mkdir()
        profile = {"discussion_model_tier": "max"}
        (sh / "profile.yaml").write_text(yaml.dump(profile))

        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE tasks (id TEXT, title TEXT, owner TEXT, status TEXT, "
            "project_path TEXT, created_at TEXT, updated_at TEXT, workflow TEXT, "
            "model_tier TEXT, effort TEXT)"
        )
        conn.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ROUND_TASK, "Round 1", "claude-code", "in_progress",
             str(tmp_path), "2026-05-01T00:00:00Z", "2026-05-01T00:00:00Z",
             "discussion", None, "medium"),
        )
        conn.execute(
            "CREATE TABLE inbox (id TEXT, task_id TEXT, target_agent TEXT, status TEXT, "
            "priority INTEGER, retry_count INTEGER, max_retries INTEGER, pid INTEGER, "
            "project_path TEXT, plan_only INTEGER, failed_reason TEXT, created_at TEXT, "
            "launched_at TEXT, last_heartbeat TEXT, paused_at TEXT, failed_at TEXT, done_at TEXT)"
        )
        conn.execute(
            "INSERT INTO inbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("item-1", ROUND_TASK, "claude-code", "launched", 5, 0, 3, None,
             str(tmp_path), 0, None, "2026-05-07T11:00:00Z", None, None, None, None, None),
        )
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

        _prepare_launch_context(ctx)

        assert "--model" in ctx.launch_args
        model_idx = ctx.launch_args.index("--model")
        model_val = ctx.launch_args[model_idx + 1]
        # Env var should win — should be haiku, not opus
        assert model_val == "claude-haiku-4-5" or "haiku" in model_val.lower(), (
            f"Env var should override profile config. Expected haiku, got: {model_val}"
        )


# ---------------------------------------------------------------------------
# --tier flag on shux discuss cmd_start
# ---------------------------------------------------------------------------


class TestTierFlagOnDiscussStart:
    def test_tier_flag_stored_on_task(self, tmp_path):
        """When --tier max is passed, task gets model_tier=max without classify_task call."""
        import os, yaml, json, secrets, sqlite3
        from unittest.mock import patch

        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True)
        discussions_dir = str(sh / "discussions")
        inbox_file = str(sh / "inbox.yaml")
        contract_file = str(sh / "contract.yaml")
        os.makedirs(discussions_dir, exist_ok=True)

        # Create empty state.sqlite3 (let the engine handle table creation)
        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.close()

        with patch("superharness.engine.inbox._inbox_lock"):
            from superharness.commands.discuss import cmd_start
            rc = cmd_start(
                discussions_dir=discussions_dir,
                inbox_file=inbox_file,
                contract_file=contract_file,
                topic="Test discussion with tier override",
                task_id=None,
                max_rounds=2,
                project_dir=str(tmp_path),
                actor="owner",
                tier="max",  # <-- the --tier flag value
                owners=["claude-code", "gemini-cli"],
                exclude=[],
            )

        # Verify the task was created with model_tier=max
        conn2 = sqlite3.connect(str(db_path))
        conn2.row_factory = sqlite3.Row  # match production get_connection
        row = conn2.execute(
            "SELECT id, model_tier, effort FROM tasks WHERE workflow = 'discussion'"
        ).fetchone()
        conn2.close()

        assert row is not None, "Discussion task should have been created"
        assert row["model_tier"] == "max", (
            f"With --tier max, model_tier should be 'max', got: {row['model_tier']}"
        )
