"""Tests for I8 acceptance criteria:
  1. watcher polls operator_commands table and transitions pending rows
  2. onboard --quick-setup skips configured sections (alias for --quick)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db, transaction
from superharness.engine import operator_commands_dao, tasks_dao
from superharness.engine.tasks_dao import TaskRow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    sh = project / ".superharness"
    sh.mkdir()
    conn = get_connection(str(project))
    init_db(conn)
    conn.close()
    return project


def _insert_task(conn, project_dir: Path, task_id: str, status: str) -> None:
    now = _now()
    tasks_dao.upsert(conn, TaskRow(
        id=task_id,
        title="Test task",
        status=status,
        owner="claude-code",
        project_path=str(project_dir),
        created_at=now,
        updated_at=now,
        version=1,
        effort=None,
        development_method=None,
        acceptance_criteria=[],
        test_types=[],
        out_of_scope=[],
        definition_of_done=[],
        context=None,
        blocked_by=[],
        parent_id=None,
        tdd=None,
        contract_locked_at=None,
    ))


# ---------------------------------------------------------------------------
# operator_commands_dao.poll_pending
# ---------------------------------------------------------------------------

class TestPollPending:
    def test_poll_returns_pending_rows(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)

        # Insert a row with status='pending' (default from insert)
        operator_commands_dao.insert(
            conn,
            idempotency_key="gw-001",
            command="approve",
            task_id="t-abc",
            sender_id="telegram",
            now=_now(),
        )
        conn.commit()

        pending = operator_commands_dao.poll_pending(conn)
        assert len(pending) == 1
        assert pending[0].command == "approve"
        assert pending[0].status == "pending"
        conn.close()

    def test_poll_excludes_executed_rows(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)

        row, _ = operator_commands_dao.insert(
            conn,
            idempotency_key="gw-002",
            command="approve",
            task_id="t-abc",
            sender_id="telegram",
            now=_now(),
        )
        operator_commands_dao.update_status(conn, row.id, status="executed", now=_now())
        conn.commit()

        assert operator_commands_dao.poll_pending(conn) == []
        conn.close()

    def test_poll_returns_fifo_order(self, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)

        operator_commands_dao.insert(conn, idempotency_key="k1", command="approve",
                                      task_id="t-1", sender_id="cli", now=_now())
        operator_commands_dao.insert(conn, idempotency_key="k2", command="reject",
                                      task_id="t-2", sender_id="cli", now=_now())
        conn.commit()

        pending = operator_commands_dao.poll_pending(conn)
        assert [r.idempotency_key for r in pending] == ["k1", "k2"]
        conn.close()


# ---------------------------------------------------------------------------
# Watcher _poll_operator_commands: transitions plan_proposed tasks
# ---------------------------------------------------------------------------

class TestWatcherPollOperatorCommands:
    def test_approve_transitions_plan_proposed(self, tmp_path: Path) -> None:
        from superharness.commands.inbox_watch import _poll_operator_commands

        project = _make_project(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)
        _insert_task(conn, project, "t-abc", "plan_proposed")
        # Insert a gateway command left as 'pending'
        operator_commands_dao.insert(
            conn,
            idempotency_key="gw-approve-t-abc",
            command="approve",
            task_id="t-abc",
            sender_id="telegram",
            now=_now(),
        )
        conn.commit()
        conn.close()

        _poll_operator_commands(str(project))

        conn2 = get_connection(str(project))
        init_db(conn2)
        task = tasks_dao.get(conn2, "t-abc")
        conn2.close()
        assert task is not None
        assert task.status == "plan_approved"

    def test_reject_transitions_plan_proposed_to_stopped(self, tmp_path: Path) -> None:
        from superharness.commands.inbox_watch import _poll_operator_commands

        project = _make_project(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)
        _insert_task(conn, project, "t-xyz", "plan_proposed")
        operator_commands_dao.insert(
            conn,
            idempotency_key="gw-reject-t-xyz",
            command="reject",
            task_id="t-xyz",
            sender_id="telegram",
            now=_now(),
        )
        conn.commit()
        conn.close()

        _poll_operator_commands(str(project))

        conn2 = get_connection(str(project))
        init_db(conn2)
        task = tasks_dao.get(conn2, "t-xyz")
        conn2.close()
        assert task.status == "stopped"

    def test_approve_skips_wrong_status(self, tmp_path: Path) -> None:
        from superharness.commands.inbox_watch import _poll_operator_commands

        project = _make_project(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)
        _insert_task(conn, project, "t-abc", "in_progress")
        operator_commands_dao.insert(
            conn,
            idempotency_key="gw-approve-t-abc-wrong",
            command="approve",
            task_id="t-abc",
            sender_id="telegram",
            now=_now(),
        )
        conn.commit()
        conn.close()

        _poll_operator_commands(str(project))

        conn2 = get_connection(str(project))
        init_db(conn2)
        task = tasks_dao.get(conn2, "t-abc")
        # Row consumed with 'skipped' status, task unchanged
        row = operator_commands_dao.get_by_key(conn2, "gw-approve-t-abc-wrong")
        conn2.close()
        assert task.status == "in_progress"
        assert row is not None
        assert row.status == "skipped"

    def test_command_marked_executed_after_processing(self, tmp_path: Path) -> None:
        from superharness.commands.inbox_watch import _poll_operator_commands

        project = _make_project(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)
        _insert_task(conn, project, "t-abc", "plan_proposed")
        operator_commands_dao.insert(
            conn,
            idempotency_key="gw-approve-exec",
            command="approve",
            task_id="t-abc",
            sender_id="telegram",
            now=_now(),
        )
        conn.commit()
        conn.close()

        _poll_operator_commands(str(project))
        # Second cycle must be idempotent — row is already 'executed'
        _poll_operator_commands(str(project))

        conn2 = get_connection(str(project))
        init_db(conn2)
        pending = operator_commands_dao.poll_pending(conn2)
        conn2.close()
        assert pending == []

    def test_missing_task_leaves_row_pending(self, tmp_path: Path) -> None:
        from superharness.commands.inbox_watch import _poll_operator_commands

        project = _make_project(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)
        # No task inserted — task_id does not exist
        operator_commands_dao.insert(
            conn,
            idempotency_key="gw-missing",
            command="approve",
            task_id="t-ghost",
            sender_id="telegram",
            now=_now(),
        )
        conn.commit()
        conn.close()

        _poll_operator_commands(str(project))

        conn2 = get_connection(str(project))
        init_db(conn2)
        pending = operator_commands_dao.poll_pending(conn2)
        conn2.close()
        # Row stays pending for next cycle
        assert len(pending) == 1
        assert pending[0].idempotency_key == "gw-missing"


# ---------------------------------------------------------------------------
# onboard --quick-setup skips configured sections
# ---------------------------------------------------------------------------

class TestOnboardQuickSetup:
    def test_quick_setup_alias_accepted(self, tmp_path: Path) -> None:
        """--quick-setup is a valid alias for --quick and must not error."""
        from click.testing import CliRunner
        from superharness.commands.onboard import cmd_onboard

        project = tmp_path / "proj"
        project.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            cmd_onboard,
            ["--project", str(project), "--quick-setup", "--non-interactive"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output

    def test_quick_setup_skips_completed_steps(self, tmp_path: Path) -> None:
        """With --quick-setup, completed steps are silently bypassed."""
        import yaml as _yaml
        from click.testing import CliRunner
        from superharness.commands.onboard import cmd_onboard, _STEPS

        project = tmp_path / "proj"
        project.mkdir()
        sh = project / ".superharness"
        sh.mkdir()

        # Mark all steps complete
        state = {"version": 1, "steps": {s: "completed" for s in _STEPS}}
        (sh / "onboarding.yaml").write_text(_yaml.dump(state))

        runner = CliRunner()
        result = runner.invoke(
            cmd_onboard,
            ["--project", str(project), "--quick-setup", "--non-interactive"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        # No step should produce output (they're all silently skipped)
        assert "[detect]" not in result.output
        assert "[init]" not in result.output

    def test_full_onboard_does_not_suppress_output(self, tmp_path: Path) -> None:
        """Without --quick-setup, non-interactive shows guidance."""
        from click.testing import CliRunner
        from superharness.commands.onboard import cmd_onboard

        project = tmp_path / "proj"
        project.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            cmd_onboard,
            ["--project", str(project), "--non-interactive"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        # Non-interactive guidance or setup output must appear
        assert len(result.output) > 0
