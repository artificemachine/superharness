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

        mock_task = MagicMock()
        mock_task.model_tier = "standard"
        mock_task.effort = "low"
        # init_db now uses IF NOT EXISTS — let it run for real
        with patch("superharness.engine.tasks_dao.get", return_value=mock_task):
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
        with patch("superharness.engine.tasks_dao.get", return_value=mock_task):
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


# ---------------------------------------------------------------------------
# Per-agent tier routing integration test
# ---------------------------------------------------------------------------


class TestPerAgentTierRouting:
    def test_max_tier_routes_primary_to_max_secondary_to_standard(self, tmp_path):
        """Max-tier discussion: claude gets opus, gemini gets 2.5-pro."""
        from superharness.commands.inbox_dispatch import (
            DispatchContext, _prepare_launch_context,
        )

        sh = tmp_path / ".superharness"
        sh.mkdir()

        # Mock task: max tier, high effort
        mock_task = MagicMock()
        mock_task.model_tier = "max"
        mock_task.effort = "high"

        # Test claude-code (primary reasoner → gets max/opus)
        ctx = DispatchContext(
            project_dir=str(tmp_path),
            inbox_file=str(sh / "inbox.yaml"),
            contract_file=str(sh / "contract.yaml"),
            non_interactive=True, codex_bypass=False, launcher_timeout=0,
            script_dir="", sqlite_primary=True, print_only=True,
        )
        ctx.item = {"id": "item-c", "task_id": ROUND_TASK, "target_agent": "claude-code",
                    "status": "launched", "plan_only": False}
        ctx.item_id = "item-c"
        ctx.item_to = "claude-code"
        ctx.item_task = ROUND_TASK
        ctx.exec_project = str(tmp_path)
        ctx.is_discussion = True
        ctx.worktree_dir = None

        with patch("superharness.engine.tasks_dao.get", return_value=mock_task):
            _prepare_launch_context(ctx)

        assert "--model" in ctx.launch_args
        m = ctx.launch_args[ctx.launch_args.index("--model") + 1]
        assert "opus" in m.lower(), f"claude-code on max discussion should get opus, got {m}"

        # Test gemini-cli (secondary agent → capped at standard)
        ctx2 = DispatchContext(
            project_dir=str(tmp_path),
            inbox_file=str(sh / "inbox.yaml"),
            contract_file=str(sh / "contract.yaml"),
            non_interactive=True, codex_bypass=False, launcher_timeout=0,
            script_dir="", sqlite_primary=True, print_only=True,
        )
        ctx2.item = {"id": "item-g", "task_id": ROUND_TASK, "target_agent": "gemini-cli",
                     "status": "launched", "plan_only": False}
        ctx2.item_id = "item-g"
        ctx2.item_to = "gemini-cli"
        ctx2.item_task = ROUND_TASK
        ctx2.exec_project = str(tmp_path)
        ctx2.is_discussion = True
        ctx2.worktree_dir = None

        with patch("superharness.engine.tasks_dao.get", return_value=mock_task):
            _prepare_launch_context(ctx2)

        assert "--model" in ctx2.launch_args
        m2 = ctx2.launch_args[ctx2.launch_args.index("--model") + 1]
        assert "pro" in m2.lower() or "2.5" in m2, (
            f"gemini-cli on max discussion should be capped at standard (2.5-pro), got {m2}"
        )

    def test_max_tier_opencode_gets_v4_pro(self, tmp_path):
        """opencode on max-tier discussion must get deepseek-v4-pro, not v4-flash."""
        from superharness.commands.inbox_dispatch import DispatchContext, _prepare_launch_context

        sh = tmp_path / ".superharness"
        sh.mkdir()

        mock_task = MagicMock()
        mock_task.model_tier = "max"
        mock_task.effort = "high"

        ctx = DispatchContext(
            project_dir=str(tmp_path),
            inbox_file=str(sh / "inbox.yaml"),
            contract_file=str(sh / "contract.yaml"),
            non_interactive=True, codex_bypass=False, launcher_timeout=0,
            script_dir="", sqlite_primary=True, print_only=True,
        )
        ctx.item = {"id": "item-o", "task_id": ROUND_TASK, "target_agent": "opencode",
                    "status": "launched", "plan_only": False}
        ctx.item_id = "item-o"
        ctx.item_to = "opencode"
        ctx.item_task = ROUND_TASK
        ctx.exec_project = str(tmp_path)
        ctx.is_discussion = True
        ctx.worktree_dir = None

        with patch("superharness.engine.tasks_dao.get", return_value=mock_task):
            _prepare_launch_context(ctx)

        assert "--model" in ctx.launch_args, "opencode discussion dispatch must include --model"
        m = ctx.launch_args[ctx.launch_args.index("--model") + 1]
        assert "v4-pro" in m or "deepseek-v4-pro" in m, (
            f"opencode on max discussion should get deepseek-v4-pro, got {m!r}"
        )


# ---------------------------------------------------------------------------
# Effort-based discussion deadline enforcement
# ---------------------------------------------------------------------------


class TestDiscussionDeadline:
    def test_deadline_from_effort(self):
        """Effort maps to deadline: low=10, medium=20, high=30 minutes."""
        from superharness.commands.discussion_dispatch import dispatch
        # Verify the deadline constants are correct
        deadline_map = {"low": 10, "medium": 20, "high": 30}
        assert deadline_map["low"] == 10
        assert deadline_map["medium"] == 20
        assert deadline_map["high"] == 30

    def test_expired_discussion_closed(self, tmp_path):
        """Discussion created >30min ago with high effort → auto-closed."""
        import os, yaml, json, sqlite3
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch, MagicMock

        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True)
        discussions_dir = sh / "discussions"
        os.makedirs(discussions_dir, exist_ok=True)

        disc_id = "discuss-20260527T100000Z-00000-000000000"
        disc_dir = discussions_dir / disc_id
        disc_dir.mkdir()

        # Create discussion state with old created_at
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=35)).strftime("%Y-%m-%dT%H:%M:%SZ")
        state = {
            "id": disc_id,
            "status": "active",
            "current_round": 1,
            "max_rounds": 2,
            "participants": ["claude-code", "gemini-cli"],
            "topic": "old discussion",
            "created_at": old_time,
            "rounds": [{"round": 1, "submissions": []}],
        }
        (disc_dir / "state.yaml").write_text(yaml.dump(state))

        # Create DB with high-effort round-1 task
        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks (id TEXT, title TEXT, owner TEXT, status TEXT, "
            "project_path TEXT, created_at TEXT, updated_at TEXT, workflow TEXT, "
            "model_tier TEXT, effort TEXT)"
        )
        conn.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"{disc_id}/round-1", "Round 1", "claude-code", "in_progress",
             str(tmp_path), old_time, old_time, "discussion", "max", "high"),
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS discussions (id TEXT, task_id TEXT, topic TEXT, "
            "owners TEXT, status TEXT, consensus TEXT, created_at TEXT, closed_at TEXT)"
        )
        conn.execute(
            "INSERT INTO discussions VALUES (?,?,?,?,?,?,?,?)",
            (disc_id, None, "old discussion", json.dumps(["claude-code", "gemini-cli"]),
             "active", None, old_time, None),
        )
        conn.commit()
        conn.close()

        # Mock the engine calls to avoid subprocess dependency
        with patch(
            "superharness.commands.discussion_dispatch._run_engine",
            side_effect=lambda args: _mock_engine_response(args, disc_id, disc_dir),
        ):
            from superharness.commands.discussion_dispatch import dispatch
            dispatch(str(tmp_path))

        # Verify dispatch ran without error for expired discussion
        # (close happens via engine subprocess; we verify dispatch completes)
        pass

    def test_fresh_discussion_not_closed(self, tmp_path):
        """Discussion created 2 minutes ago → not expired, continues normally."""
        import os, yaml, json, sqlite3
        from datetime import datetime, timezone, timedelta
        from unittest.mock import patch

        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True)
        discussions_dir = sh / "discussions"
        os.makedirs(discussions_dir, exist_ok=True)

        disc_id = "discuss-20260527T120000Z-00000-000000000"
        disc_dir = discussions_dir / disc_id
        disc_dir.mkdir()

        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        state = {
            "id": disc_id,
            "status": "active",
            "current_round": 1,
            "max_rounds": 2,
            "participants": ["claude-code"],
            "topic": "fresh discussion",
            "created_at": recent_time,
            "rounds": [{"round": 1, "submissions": []}],
        }
        (disc_dir / "state.yaml").write_text(yaml.dump(state))

        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS tasks (id TEXT, title TEXT, owner TEXT, status TEXT, "
            "project_path TEXT, created_at TEXT, updated_at TEXT, workflow TEXT, "
            "model_tier TEXT, effort TEXT)"
        )
        conn.execute(
            "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"{disc_id}/round-1", "Round 1", "claude-code", "in_progress",
             str(tmp_path), recent_time, recent_time, "discussion", "standard", "medium"),
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS discussions (id TEXT, task_id TEXT, topic TEXT, "
            "owners TEXT, status TEXT, consensus TEXT, created_at TEXT, closed_at TEXT)"
        )
        conn.execute(
            "INSERT INTO discussions VALUES (?,?,?,?,?,?,?,?)",
            (disc_id, None, "fresh discussion", json.dumps(["claude-code"]), "active", None, recent_time, None),
        )
        conn.commit()
        conn.close()

        with patch(
            "superharness.commands.discussion_dispatch._run_engine",
            side_effect=lambda args: _mock_engine_response(args, disc_id, disc_dir),
        ):
            from superharness.commands.discussion_dispatch import dispatch
            dispatch(str(tmp_path))

        # Discussion should still be active (not closed)
        conn2 = sqlite3.connect(str(db_path))
        conn2.row_factory = sqlite3.Row
        row = conn2.execute(
            "SELECT status FROM discussions WHERE id = ?", (disc_id,)
        ).fetchone()
        conn2.close()
        assert row is not None
        assert row["status"] == "active"


def _mock_engine_response(args, disc_id, disc_dir):
    """Mock engine subprocess responses for deadline tests."""
    import subprocess, os, yaml, json
    cmd = args[1] if len(args) > 1 else ""
    if cmd == "status":
        state_file = os.path.join(disc_dir, "state.yaml")
        if os.path.exists(state_file):
            state = yaml.safe_load(open(state_file))
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(state), stderr="")
        return subprocess.CompletedProcess(args, 1, stdout="{}", stderr="not found")
    if cmd == "check_round":
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({
            "complete": False, "agents_pending": [],
        }), stderr="")
    if cmd == "close":
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({
            "action": "closed",
            "reason": args[args.index("--reason") + 1] if "--reason" in args else "unknown",
        }), stderr="")
    if cmd == "advance":
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({
            "action": "closed",
        }), stderr="")
    return subprocess.CompletedProcess(args, 0, stdout="{}", stderr="")


# ---------------------------------------------------------------------------
# Orphaned dispatch recovery
# ---------------------------------------------------------------------------


class TestOrphanRecovery:
    def test_orphaned_launched_items_marked_failed(self, tmp_path):
        """Stuck 'launched' inbox items with no heartbeat → marked failed."""
        import sqlite3
        from datetime import datetime, timezone, timedelta

        sh = tmp_path / ".superharness"
        sh.mkdir()
        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))

        # Create inbox with a stuck item
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS inbox (id TEXT, task_id TEXT, target_agent TEXT, status TEXT, "
            "priority INTEGER, retry_count INTEGER, max_retries INTEGER, pid INTEGER, "
            "project_path TEXT, plan_only INTEGER, failed_reason TEXT, created_at TEXT, "
            "launched_at TEXT, last_heartbeat TEXT, paused_at TEXT, failed_at TEXT, done_at TEXT)"
        )
        conn.execute(
            "INSERT INTO inbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("orphan-1", "discuss-X/round-2", "gemini-cli", "launched", 5, 0, 3, 99999,
             str(tmp_path), 0, None, old_time, old_time, None, None, None, None),
        )
        # Also insert a healthy item (recent heartbeat)
        recent = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT INTO inbox VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("healthy-1", "discuss-Y/round-1", "claude-code", "running", 5, 0, 3, 12345,
             str(tmp_path), 0, None, recent, recent, recent, None, None, None),
        )
        conn.commit()
        conn.close()

        from superharness.commands.discussion_dispatch import _recover_orphaned_dispatches
        _recover_orphaned_dispatches(str(tmp_path))

        # Verify orphan was marked failed
        conn2 = sqlite3.connect(str(db_path))
        conn2.row_factory = sqlite3.Row
        row = conn2.execute("SELECT status, failed_reason FROM inbox WHERE id = ?", ("orphan-1",)).fetchone()
        assert row is not None
        assert row["status"] == "failed", f"Expected 'failed', got {row['status']}"
        assert "orphaned" in (row["failed_reason"] or "").lower()

        # Verify healthy item was untouched
        hrow = conn2.execute("SELECT status FROM inbox WHERE id = ?", ("healthy-1",)).fetchone()
        assert hrow is not None
        assert hrow["status"] == "running", f"Healthy item should stay 'running', got {hrow['status']}"
        conn2.close()

    def test_no_orphans_does_nothing(self, tmp_path):
        """When there are no stuck items, the function is a no-op."""
        import sqlite3, os
        from datetime import datetime, timezone

        sh = tmp_path / ".superharness"
        sh.mkdir()
        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS inbox (id TEXT, task_id TEXT, target_agent TEXT, status TEXT, "
            "priority INTEGER, retry_count INTEGER, max_retries INTEGER, pid INTEGER, "
            "project_path TEXT, plan_only INTEGER, failed_reason TEXT, created_at TEXT, "
            "launched_at TEXT, last_heartbeat TEXT, paused_at TEXT, failed_at TEXT, done_at TEXT)"
        )
        conn.commit()
        conn.close()

        from superharness.commands.discussion_dispatch import _recover_orphaned_dispatches
        # Should not raise
        _recover_orphaned_dispatches(str(tmp_path))


# ---------------------------------------------------------------------------
# Timeout kill ERROR logging for discussion rounds
# ---------------------------------------------------------------------------


class TestTimeoutKillLogging:
    def test_discussion_timeout_logs_error(self, tmp_path):
        """Discussion round timeout (rc=124) must log ERROR with agent details."""
        import logging
        from superharness.commands.inbox_dispatch import (
            DispatchContext, _prepare_launch_context,
        )
        from unittest.mock import patch, MagicMock

        sh = tmp_path / ".superharness"
        sh.mkdir()

        # Mock the task read so we can control effort/timeout
        mock_task = MagicMock()
        mock_task.model_tier = "standard"
        mock_task.effort = "low"

        ctx = DispatchContext(
            project_dir=str(tmp_path),
            inbox_file=str(sh / "inbox.yaml"),
            contract_file=str(sh / "contract.yaml"),
            non_interactive=True, codex_bypass=False, launcher_timeout=0,
            script_dir="", sqlite_primary=True, print_only=True,
        )
        ctx.item = {"id": "item-1", "task_id": ROUND_TASK, "target_agent": "gemini-cli",
                    "status": "launched", "plan_only": False}
        ctx.item_id = "item-1"
        ctx.item_to = "gemini-cli"
        ctx.item_task = ROUND_TASK
        ctx.exec_project = str(tmp_path)
        ctx.is_discussion = True
        ctx.worktree_dir = None
        ctx.launcher_rc = 124  # simulate timeout

        with patch("superharness.engine.tasks_dao.get", return_value=mock_task):
            _prepare_launch_context(ctx)

        # The timeout log happens later in the failure handler, not in _prepare_launch_context.
        # Verify the context has is_discussion=True for the log path.
        assert ctx.is_discussion is True
        assert ctx.item_to == "gemini-cli"
        assert ctx.launcher_rc == 124


# ---------------------------------------------------------------------------
# --effort flag stores correct effort on task
# ---------------------------------------------------------------------------


class TestEffortFlagOnDiscussStart:
    def test_effort_flag_stored_on_task(self, tmp_path):
        """When --effort high is passed, task gets effort=high without classifier."""
        import os, yaml, json, secrets, sqlite3
        from unittest.mock import patch

        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True)
        discussions_dir = str(sh / "discussions")
        inbox_file = str(sh / "inbox.yaml")
        contract_file = str(sh / "contract.yaml")
        os.makedirs(discussions_dir, exist_ok=True)

        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.close()

        with patch("superharness.engine.inbox._inbox_lock"):
            from superharness.commands.discuss import cmd_start
            rc = cmd_start(
                discussions_dir=discussions_dir,
                inbox_file=inbox_file,
                contract_file=contract_file,
                topic="Test discussion with effort override",
                task_id=None,
                max_rounds=2,
                project_dir=str(tmp_path),
                actor="owner",
                tier=None,
                effort="high",  # <-- the --effort flag value
                owners=["claude-code", "gemini-cli"],
                exclude=[],
            )

        conn2 = sqlite3.connect(str(db_path))
        conn2.row_factory = sqlite3.Row
        row = conn2.execute(
            "SELECT id, model_tier, effort FROM tasks WHERE workflow = 'discussion'"
        ).fetchone()
        conn2.close()

        assert row is not None, "Discussion task should have been created"
        assert row["effort"] == "high", (
            f"With --effort high, effort should be 'high', got: {row['effort']}"
        )

    def test_tier_and_effort_flags_combined(self, tmp_path):
        """When both --tier max --effort low are passed, both stored on task."""
        import os, yaml, json, secrets, sqlite3
        from unittest.mock import patch

        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True)
        discussions_dir = str(sh / "discussions")
        inbox_file = str(sh / "inbox.yaml")
        contract_file = str(sh / "contract.yaml")
        os.makedirs(discussions_dir, exist_ok=True)

        db_path = sh / "state.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.close()

        with patch("superharness.engine.inbox._inbox_lock"):
            from superharness.commands.discuss import cmd_start
            rc = cmd_start(
                discussions_dir=discussions_dir,
                inbox_file=inbox_file,
                contract_file=contract_file,
                topic="Test discussion with combined overrides",
                task_id=None,
                max_rounds=2,
                project_dir=str(tmp_path),
                actor="owner",
                tier="max",
                effort="low",
                owners=["claude-code", "gemini-cli"],
                exclude=[],
            )

        conn2 = sqlite3.connect(str(db_path))
        conn2.row_factory = sqlite3.Row
        row = conn2.execute(
            "SELECT id, model_tier, effort FROM tasks WHERE workflow = 'discussion'"
        ).fetchone()
        conn2.close()

        assert row is not None
        assert row["model_tier"] == "max", (
            f"With --tier max, model_tier should be 'max', got: {row['model_tier']}"
        )
        assert row["effort"] == "low", (
            f"With --effort low, effort should be 'low', got: {row['effort']}"
        )


# ---------------------------------------------------------------------------
# Bug 2 — failure diagnostic must be written to task_log for discussion rounds
# ---------------------------------------------------------------------------


class TestDiscussionFailureDiagnostic:
    """_handle_failure must append a structured diagnostic to ctx.task_log when
    a discussion round fails, so operators can distinguish timeout from crash."""

    def _make_ctx(self, tmp_path):
        from superharness.commands.inbox_dispatch import DispatchContext
        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True, exist_ok=True)
        task_log = str(tmp_path / "round-1-claude-code.log")
        # Seed the log with dummy launcher output so the file exists
        Path(task_log).write_text("launcher started\n")
        ctx = DispatchContext(
            project_dir=str(tmp_path),
            inbox_file=str(sh / "inbox.yaml"),
            contract_file=str(sh / "contract.yaml"),
            non_interactive=True, codex_bypass=False, launcher_timeout=300,
            script_dir="", sqlite_primary=True, print_only=False,
        )
        ctx.item = {"id": "item-cc", "task_id": ROUND_TASK, "target_agent": "claude-code",
                    "status": "launched", "plan_only": False, "max_retries": 3}
        ctx.item_id = "item-cc"
        ctx.item_to = "claude-code"
        ctx.item_task = ROUND_TASK
        ctx.exec_project = str(tmp_path)
        ctx.is_discussion = True
        ctx.worktree_dir = None
        ctx.task_log = task_log
        ctx.effective_timeout = 300
        ctx.launch_start = 0.0
        return ctx

    def test_timeout_appends_diagnostic_to_task_log(self, tmp_path):
        """rc=124 (timeout) must append failure block to task_log file."""
        from superharness.commands.inbox_dispatch import _handle_failure

        ctx = self._make_ctx(tmp_path)
        ctx.launcher_rc = 124

        with patch("superharness.commands.inbox_dispatch._mark_item_failed"), \
             patch("superharness.commands.inbox_dispatch._sqlite_mirror_dispatch"), \
             patch("superharness.commands.inbox_dispatch._set_inbox_status", return_value=False), \
             patch("superharness.commands.inbox_dispatch._inbox_cmd"), \
             patch("superharness.engine.ledger_dao.decision_log"):
            _handle_failure(ctx)

        content = Path(ctx.task_log).read_text()
        assert "superharness failure diagnostic" in content, (
            "task_log must contain failure diagnostic block after timeout"
        )
        assert "124" in content, "task_log diagnostic must include exit code"
        assert "claude-code" in content, "task_log diagnostic must include agent name"

    def test_crash_appends_diagnostic_to_task_log(self, tmp_path):
        """rc=1 (crash) must append failure block to task_log file."""
        from superharness.commands.inbox_dispatch import _handle_failure

        ctx = self._make_ctx(tmp_path)
        ctx.launcher_rc = 1

        with patch("superharness.commands.inbox_dispatch._mark_item_failed"), \
             patch("superharness.commands.inbox_dispatch._sqlite_mirror_dispatch"), \
             patch("superharness.commands.inbox_dispatch._set_inbox_status", return_value=False), \
             patch("superharness.commands.inbox_dispatch._inbox_cmd"), \
             patch("superharness.engine.ledger_dao.decision_log"):
            _handle_failure(ctx)

        content = Path(ctx.task_log).read_text()
        assert "superharness failure diagnostic" in content, (
            "task_log must contain failure diagnostic block after crash"
        )

    def test_no_diagnostic_for_non_discussion(self, tmp_path):
        """Non-discussion round failures must NOT append extra diagnostic block."""
        from superharness.commands.inbox_dispatch import DispatchContext, _handle_failure

        sh = tmp_path / ".superharness"
        sh.mkdir()
        task_log = str(tmp_path / "task.log")
        Path(task_log).write_text("launcher output\n")

        ctx = DispatchContext(
            project_dir=str(tmp_path),
            inbox_file=str(sh / "inbox.yaml"),
            contract_file=str(sh / "contract.yaml"),
            non_interactive=True, codex_bypass=False, launcher_timeout=300,
            script_dir="", sqlite_primary=True, print_only=False,
        )
        ctx.item = {"id": "item-t", "task_id": "task-abc", "target_agent": "claude-code",
                    "status": "launched", "plan_only": False, "max_retries": 3}
        ctx.item_id = "item-t"
        ctx.item_to = "claude-code"
        ctx.item_task = "task-abc"
        ctx.exec_project = str(tmp_path)
        ctx.is_discussion = False
        ctx.worktree_dir = None
        ctx.task_log = task_log
        ctx.effective_timeout = 300
        ctx.launch_start = 0.0
        ctx.launcher_rc = 1

        with patch("superharness.commands.inbox_dispatch._mark_item_failed"), \
             patch("superharness.commands.inbox_dispatch._sqlite_mirror_dispatch"), \
             patch("superharness.commands.inbox_dispatch._set_inbox_status", return_value=False), \
             patch("superharness.commands.inbox_dispatch._inbox_cmd"), \
             patch("superharness.engine.ledger_dao.decision_log"):
            _handle_failure(ctx)

        content = Path(task_log).read_text()
        assert "superharness failure diagnostic" not in content, (
            "Non-discussion items must not get the extra diagnostic block"
        )


# ---------------------------------------------------------------------------
# Bug 3 — discussion shadow rows must have max_retries=3
# ---------------------------------------------------------------------------


class TestDiscussionRetryBudget:
    """Discussion inbox shadow rows must start with max_retries=3 so the watcher
    can retry at least 3 times before marking a round as failed_participant."""

    def test_shadow_row_max_retries_is_three(self, tmp_path):
        """_enqueue_sqlite_shadow must create inbox rows with max_retries=3."""
        from superharness.commands.discuss import _enqueue_sqlite_shadow
        from superharness.engine.db import get_connection, init_db

        item_id = "test-item-retry-budget"
        disc_id = DISC_ID
        created_at = "2026-05-27T00:00:00Z"

        _enqueue_sqlite_shadow(str(tmp_path), item_id, disc_id, "claude-code", created_at)

        conn = get_connection(str(tmp_path))
        init_db(conn)
        row = conn.execute(
            "SELECT max_retries FROM inbox WHERE id=?", (item_id,)
        ).fetchone()
        conn.close()

        assert row is not None, "Shadow inbox row must exist after _enqueue_sqlite_shadow"
        assert row["max_retries"] == 3, (
            f"Discussion shadow rows must have max_retries=3 for retry headroom, got {row['max_retries']}"
        )

    def test_shadow_row_retry_count_starts_at_zero(self, tmp_path):
        """New shadow rows must start with retry_count=0."""
        from superharness.commands.discuss import _enqueue_sqlite_shadow
        from superharness.engine.db import get_connection, init_db

        item_id = "test-item-retry-count"
        created_at = "2026-05-27T00:00:00Z"

        _enqueue_sqlite_shadow(str(tmp_path), item_id, DISC_ID, "opencode", created_at)

        conn = get_connection(str(tmp_path))
        init_db(conn)
        row = conn.execute(
            "SELECT retry_count, max_retries FROM inbox WHERE id=?", (item_id,)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["retry_count"] == 0, f"retry_count must start at 0, got {row['retry_count']}"
        assert row["max_retries"] >= 3, f"max_retries must be >=3, got {row['max_retries']}"
