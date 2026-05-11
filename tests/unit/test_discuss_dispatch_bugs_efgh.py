"""Regression tests for the four open bugs in
docs/bugs/2026-05-11_discuss_dispatch_bugs.md (G, F, E, H).

G — discussion_dispatch must not re-enqueue a participant who already
    has a round-N-<agent>.yaml on disk, nor one whose retry budget is
    exhausted.
F — cmd_check_round must count an agent as "submitted" when the YAML
    artifact exists, even without a discussion_rounds DB row. This
    also covers --verdict abstain when the row write succeeds.
E — _handle_failure must promote a non-zero launcher exit to "done"
    when the round-N-<agent>.yaml is present on disk; terminal escape
    garbage at the tail of the launcher output should not lose a real
    submission.
H — SUPERHARNESS_DISCUSSION_ROUND_TIMEOUT_SECONDS overrides the
    bundled 900s discussion-round cap when set.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest import mock

import pytest


DISC_ID = "discuss-20260511T120000Z-test"
ROUND_TASK = f"{DISC_ID}/round-1"


# ---------------------------------------------------------------------------
# Bug F / G — file-on-disk counts as submitted in cmd_check_round
# ---------------------------------------------------------------------------


def _seed_minimal_project(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "handoffs").mkdir()
    return tmp_path


def _seed_task_row(project: Path, task_id: str) -> None:
    """Insert a tasks row so the inbox FK on task_id is satisfied."""
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(project))
    init_db(conn)
    conn.execute(
        "INSERT OR IGNORE INTO tasks (id, title, status, created_at) VALUES (?, ?, ?, ?)",
        (task_id, "test", "todo", "2026-05-11T12:00:00Z"),
    )
    conn.commit()
    conn.close()


def _seed_discussion(project: Path, owners: list[str]) -> Path:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import discussions_dao

    conn = get_connection(str(project))
    init_db(conn)
    discussions_dao.create(
        conn,
        id=DISC_ID,
        topic="bug-efgh repro",
        owners=owners,
        task_id=None,
        now="2026-05-11T12:00:00Z",
    )
    conn.commit()
    conn.close()

    disc_dir = project / ".superharness" / "discussions" / DISC_ID
    disc_dir.mkdir(parents=True)
    return disc_dir


class TestCheckRoundCountsFileOnDisk:
    def test_yaml_on_disk_marks_agent_done(self, tmp_path):
        """Bug G/F core: an agent whose round-N-<agent>.yaml exists must
        NOT appear in agents_pending, even with no discussion_rounds row."""
        project = _seed_minimal_project(tmp_path)
        disc_dir = _seed_discussion(project, owners=["claude-code", "codex-cli"])

        # claude-code wrote its YAML but never called `shux discuss submit`
        (disc_dir / "round-1-claude-code.yaml").write_text("verdict: partial\n")

        from superharness.engine.discussion import cmd_check_round
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_check_round(str(disc_dir), 1)
        import json
        result = json.loads(buf.getvalue())

        assert "claude-code" in result["agents_done"], (
            "Agent with round-1-<agent>.yaml on disk must count as done. "
            "Without this, dispatch re-enqueues already-submitted agents (Bug G)."
        )
        assert "claude-code" not in result["agents_pending"]
        assert "codex-cli" in result["agents_pending"]
        assert result["complete"] is False

    def test_missing_files_keeps_agents_pending(self, tmp_path):
        """Sanity: with no YAMLs and no DB rows, every owner is pending."""
        project = _seed_minimal_project(tmp_path)
        disc_dir = _seed_discussion(project, owners=["claude-code", "codex-cli"])

        from superharness.engine.discussion import cmd_check_round
        import io
        import contextlib
        import json

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_check_round(str(disc_dir), 1)
        result = json.loads(buf.getvalue())

        assert set(result["agents_pending"]) == {"claude-code", "codex-cli"}
        assert result["agents_done"] == []
        assert result["complete"] is False


# ---------------------------------------------------------------------------
# Bug G — discussion_dispatch idempotence + retry cap
# ---------------------------------------------------------------------------


class TestDispatcherIdempotence:
    def test_retry_exhausted_helper_returns_true_at_max(self, tmp_path):
        """_retry_exhausted must read the latest inbox row for
        (agent, task_key) and report True when retry_count >= max_retries."""
        from superharness.engine.db import get_connection, init_db
        from superharness.commands.discussion_dispatch import _retry_exhausted

        project = _seed_minimal_project(tmp_path)
        _seed_task_row(project, ROUND_TASK)
        conn = get_connection(str(project))
        init_db(conn)
        conn.execute(
            "INSERT INTO inbox "
            "(id, task_id, target_agent, status, priority, retry_count, max_retries, project_path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("item-1", ROUND_TASK, "codex-cli", "failed", 1, 3, 3, str(project), "2026-05-11T12:00:00Z"),
        )
        conn.commit()
        conn.close()

        assert _retry_exhausted(str(project), "codex-cli", ROUND_TASK) is True

    def test_retry_exhausted_helper_returns_false_below_max(self, tmp_path):
        from superharness.engine.db import get_connection, init_db
        from superharness.commands.discussion_dispatch import _retry_exhausted

        project = _seed_minimal_project(tmp_path)
        _seed_task_row(project, ROUND_TASK)
        conn = get_connection(str(project))
        init_db(conn)
        conn.execute(
            "INSERT INTO inbox "
            "(id, task_id, target_agent, status, priority, retry_count, max_retries, project_path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("item-1", ROUND_TASK, "codex-cli", "failed", 1, 1, 3, str(project), "2026-05-11T12:00:00Z"),
        )
        conn.commit()
        conn.close()

        assert _retry_exhausted(str(project), "codex-cli", ROUND_TASK) is False

    def test_retry_exhausted_helper_returns_false_when_no_row(self, tmp_path):
        from superharness.commands.discussion_dispatch import _retry_exhausted
        project = _seed_minimal_project(tmp_path)
        # No inbox row exists yet
        assert _retry_exhausted(str(project), "codex-cli", ROUND_TASK) is False


# ---------------------------------------------------------------------------
# Bug E — non-zero launcher RC + YAML present → mark done not failed
# ---------------------------------------------------------------------------


class TestHandleFailureRespectsYamlArtifact:
    def test_discussion_yaml_present_promotes_to_done(self, tmp_path):
        """When the launcher exits non-zero but the round YAML is on
        disk, _handle_failure must mark the inbox item 'done', not
        'failed'. This guards Bug E (terminal-escape false fail)."""
        from superharness.commands.inbox_dispatch import (
            DispatchContext, _handle_failure
        )

        project = _seed_minimal_project(tmp_path)
        _seed_task_row(project, ROUND_TASK)
        disc_dir = project / ".superharness" / "discussions" / DISC_ID
        disc_dir.mkdir(parents=True)
        (disc_dir / "round-1-claude-code.yaml").write_text("verdict: partial\n")

        # Seed an inbox row in 'launched' state
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(str(project))
        init_db(conn)
        conn.execute(
            "INSERT INTO inbox "
            "(id, task_id, target_agent, status, priority, retry_count, max_retries, project_path, created_at, launched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("item-1", ROUND_TASK, "claude-code", "launched", 1, 0, 3,
             str(project), "2026-05-11T12:00:00Z", "2026-05-11T12:00:01Z"),
        )
        conn.commit()
        conn.close()

        ctx = DispatchContext(
            project_dir=str(project),
            inbox_file=str(project / ".superharness" / "inbox.yaml"),
            contract_file=str(project / ".superharness" / "contract.yaml"),
            non_interactive=True,
            codex_bypass=False,
            launcher_timeout=900,
            script_dir="",
            sqlite_primary=True,
            print_only=False,
        )
        ctx.item = {"id": "item-1", "task_id": ROUND_TASK, "target_agent": "claude-code"}
        ctx.item_id = "item-1"
        ctx.item_to = "claude-code"
        ctx.item_task = ROUND_TASK
        ctx.exec_project = str(project)
        ctx.is_discussion = True
        ctx.launcher_rc = 1  # Non-zero — would have been classified failed
        ctx.task_log = ""
        ctx.launch_start = 0.0
        ctx.effective_timeout = 900

        rc = _handle_failure(ctx)
        assert rc == 0, "handle_failure must early-return success when YAML present"

        # Verify the inbox row was promoted to done
        conn = get_connection(str(project))
        row = conn.execute(
            "SELECT status FROM inbox WHERE id=?", ("item-1",)
        ).fetchone()
        conn.close()
        assert row["status"] == "done", (
            f"inbox status must be 'done' when launcher rc!=0 but YAML present, "
            f"got '{row['status']}'"
        )

    def test_permanent_block_still_fails_even_with_yaml(self, tmp_path):
        """Exit code 2 means lifecycle-gate permanent block. The YAML
        promotion must NOT override that signal."""
        from superharness.commands.inbox_dispatch import (
            DispatchContext, _handle_failure
        )

        project = _seed_minimal_project(tmp_path)
        _seed_task_row(project, ROUND_TASK)
        disc_dir = project / ".superharness" / "discussions" / DISC_ID
        disc_dir.mkdir(parents=True)
        (disc_dir / "round-1-claude-code.yaml").write_text("verdict: partial\n")

        from superharness.engine.db import get_connection, init_db
        conn = get_connection(str(project))
        init_db(conn)
        conn.execute(
            "INSERT INTO inbox "
            "(id, task_id, target_agent, status, priority, retry_count, max_retries, project_path, created_at, launched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("item-2", ROUND_TASK, "claude-code", "launched", 1, 0, 3,
             str(project), "2026-05-11T12:00:00Z", "2026-05-11T12:00:01Z"),
        )
        conn.commit()
        conn.close()

        ctx = DispatchContext(
            project_dir=str(project),
            inbox_file=str(project / ".superharness" / "inbox.yaml"),
            contract_file=str(project / ".superharness" / "contract.yaml"),
            non_interactive=True,
            codex_bypass=False,
            launcher_timeout=900,
            script_dir="",
            sqlite_primary=True,
            print_only=False,
        )
        ctx.item = {"id": "item-2", "task_id": ROUND_TASK, "target_agent": "claude-code", "max_retries": 3}
        ctx.item_id = "item-2"
        ctx.item_to = "claude-code"
        ctx.item_task = ROUND_TASK
        ctx.exec_project = str(project)
        ctx.is_discussion = True
        ctx.launcher_rc = 2  # permanent block
        ctx.task_log = ""
        ctx.launch_start = 0.0
        ctx.effective_timeout = 900

        rc = _handle_failure(ctx)
        # rc must NOT be 0 — permanent block should fail, not promote to done
        assert rc != 0, "Exit code 2 must still fail even with YAML present"


# ---------------------------------------------------------------------------
# Bug H — env var overrides discussion round timeout
# ---------------------------------------------------------------------------


class TestDiscussionRoundTimeoutEnvOverride:
    def test_env_var_overrides_default_timeout(self, tmp_path, monkeypatch):
        from superharness.commands.inbox_dispatch import (
            DispatchContext, _prepare_launch_context,
            DISCUSSION_ROUND_TIMEOUT_SECONDS,
        )

        monkeypatch.setenv("SUPERHARNESS_DISCUSSION_ROUND_TIMEOUT_SECONDS", "1800")

        ctx = DispatchContext(
            project_dir=str(tmp_path),
            inbox_file=str(tmp_path / "inbox.yaml"),
            contract_file=str(tmp_path / "contract.yaml"),
            non_interactive=True,
            codex_bypass=False,
            launcher_timeout=0,
            script_dir="",
            sqlite_primary=True,
            print_only=True,
        )
        ctx.item = {"id": "i-1", "task_id": ROUND_TASK, "target_agent": "claude-code", "plan_only": False}
        ctx.item_id = "i-1"
        ctx.item_to = "claude-code"
        ctx.item_task = ROUND_TASK
        ctx.exec_project = str(tmp_path)
        ctx.is_discussion = True
        ctx.worktree_dir = None
        ctx.effective_timeout = 0

        _prepare_launch_context(ctx)

        assert ctx.effective_timeout == 1800, (
            f"env var must override default {DISCUSSION_ROUND_TIMEOUT_SECONDS}s; "
            f"got {ctx.effective_timeout}"
        )

    def test_unset_env_falls_back_to_bundled_default(self, tmp_path, monkeypatch):
        from superharness.commands.inbox_dispatch import (
            DispatchContext, _prepare_launch_context,
            DISCUSSION_ROUND_TIMEOUT_SECONDS,
        )

        monkeypatch.delenv("SUPERHARNESS_DISCUSSION_ROUND_TIMEOUT_SECONDS", raising=False)

        ctx = DispatchContext(
            project_dir=str(tmp_path),
            inbox_file=str(tmp_path / "inbox.yaml"),
            contract_file=str(tmp_path / "contract.yaml"),
            non_interactive=True,
            codex_bypass=False,
            launcher_timeout=0,
            script_dir="",
            sqlite_primary=True,
            print_only=True,
        )
        ctx.item = {"id": "i-2", "task_id": ROUND_TASK, "target_agent": "claude-code", "plan_only": False}
        ctx.item_id = "i-2"
        ctx.item_to = "claude-code"
        ctx.item_task = ROUND_TASK
        ctx.exec_project = str(tmp_path)
        ctx.is_discussion = True
        ctx.worktree_dir = None
        ctx.effective_timeout = 0

        _prepare_launch_context(ctx)
        assert ctx.effective_timeout == DISCUSSION_ROUND_TIMEOUT_SECONDS

    def test_invalid_env_value_falls_back_to_default(self, tmp_path, monkeypatch):
        from superharness.commands.inbox_dispatch import (
            DispatchContext, _prepare_launch_context,
            DISCUSSION_ROUND_TIMEOUT_SECONDS,
        )

        monkeypatch.setenv("SUPERHARNESS_DISCUSSION_ROUND_TIMEOUT_SECONDS", "not-an-int")

        ctx = DispatchContext(
            project_dir=str(tmp_path),
            inbox_file=str(tmp_path / "inbox.yaml"),
            contract_file=str(tmp_path / "contract.yaml"),
            non_interactive=True,
            codex_bypass=False,
            launcher_timeout=0,
            script_dir="",
            sqlite_primary=True,
            print_only=True,
        )
        ctx.item = {"id": "i-3", "task_id": ROUND_TASK, "target_agent": "claude-code", "plan_only": False}
        ctx.item_id = "i-3"
        ctx.item_to = "claude-code"
        ctx.item_task = ROUND_TASK
        ctx.exec_project = str(tmp_path)
        ctx.is_discussion = True
        ctx.worktree_dir = None
        ctx.effective_timeout = 0

        _prepare_launch_context(ctx)
        assert ctx.effective_timeout == DISCUSSION_ROUND_TIMEOUT_SECONDS
