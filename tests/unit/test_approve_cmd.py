"""Tests for I7: shux approve CLI command.

Acceptance criteria:
  - shux approve writes an operator_command row
  - shux approve is idempotent on duplicate call
"""
from __future__ import annotations

from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine import operator_commands_dao, tasks_dao
from superharness.engine.tasks_dao import TaskRow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(conn, project_dir: Path, task_id: str, status: str = "plan_proposed"):
    """Insert a minimal task row for testing."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir()
    return tmp_path


@pytest.fixture()
def db_conn(project_dir: Path):
    conn = get_connection(str(project_dir))
    init_db(conn)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# shux approve writes operator_command row
# ---------------------------------------------------------------------------

class TestApproveWritesRow:
    def test_approve_creates_operator_command_row(
        self, project_dir: Path, db_conn
    ) -> None:
        from superharness.commands.approve import run_approve

        _make_task(db_conn, project_dir, "t-001", status="plan_proposed")
        db_conn.commit()

        rc = run_approve(project_dir, "t-001", command="approve")
        assert rc == 0

        # Verify the row exists
        row = operator_commands_dao.get_by_key(db_conn, "cli-approve-t-001")
        assert row is not None
        assert row.command == "approve"
        assert row.task_id == "t-001"
        assert row.sender_id == "cli"
        assert row.status == "executed"

    def test_approve_transitions_task_to_plan_approved(
        self, project_dir: Path, db_conn
    ) -> None:
        from superharness.commands.approve import run_approve

        _make_task(db_conn, project_dir, "t-002", status="plan_proposed")
        db_conn.commit()

        rc = run_approve(project_dir, "t-002", command="approve")
        assert rc == 0

        task = tasks_dao.get(db_conn, "t-002")
        assert task is not None
        assert task.status == "plan_approved"

    def test_reject_transitions_task_to_stopped(
        self, project_dir: Path, db_conn
    ) -> None:
        from superharness.commands.approve import run_approve

        _make_task(db_conn, project_dir, "t-003", status="plan_proposed")
        db_conn.commit()

        rc = run_approve(project_dir, "t-003", command="reject")
        assert rc == 0

        task = tasks_dao.get(db_conn, "t-003")
        assert task is not None
        assert task.status == "stopped"

    def test_reject_creates_operator_command_row_with_reject(
        self, project_dir: Path, db_conn
    ) -> None:
        from superharness.commands.approve import run_approve

        _make_task(db_conn, project_dir, "t-004", status="plan_proposed")
        db_conn.commit()

        run_approve(project_dir, "t-004", command="reject")

        row = operator_commands_dao.get_by_key(db_conn, "cli-reject-t-004")
        assert row is not None
        assert row.command == "reject"

    def test_unknown_task_returns_error(
        self, project_dir: Path, db_conn
    ) -> None:
        from superharness.commands.approve import run_approve

        # No task created
        rc = run_approve(project_dir, "t-nonexistent", command="approve")
        assert rc == 1

    def test_unknown_command_returns_error(
        self, project_dir: Path, db_conn
    ) -> None:
        from superharness.commands.approve import run_approve

        rc = run_approve(project_dir, "t-001", command="bogus")
        assert rc == 1


# ---------------------------------------------------------------------------
# shux approve is idempotent on duplicate call
# ---------------------------------------------------------------------------

class TestApproveIdempotent:
    def test_second_call_returns_zero(
        self, project_dir: Path, db_conn
    ) -> None:
        from superharness.commands.approve import run_approve

        _make_task(db_conn, project_dir, "t-idem1", status="plan_proposed")
        db_conn.commit()

        rc1 = run_approve(project_dir, "t-idem1", command="approve")
        rc2 = run_approve(project_dir, "t-idem1", command="approve")

        assert rc1 == 0
        assert rc2 == 0, "Duplicate approve must return 0 (idempotent)"

    def test_second_call_does_not_create_new_row(
        self, project_dir: Path, db_conn
    ) -> None:
        from superharness.commands.approve import run_approve

        _make_task(db_conn, project_dir, "t-idem2", status="plan_proposed")
        db_conn.commit()

        run_approve(project_dir, "t-idem2", command="approve")
        run_approve(project_dir, "t-idem2", command="approve")

        # Still exactly one row with this idempotency key
        cursor = db_conn.execute(
            "SELECT COUNT(*) FROM operator_commands WHERE idempotency_key = ?",
            ("cli-approve-t-idem2",),
        )
        count = cursor.fetchone()[0]
        assert count == 1, "Only one operator_command row should exist after duplicate calls"

    def test_task_status_unchanged_on_second_call(
        self, project_dir: Path, db_conn
    ) -> None:
        from superharness.commands.approve import run_approve

        _make_task(db_conn, project_dir, "t-idem3", status="plan_proposed")
        db_conn.commit()

        run_approve(project_dir, "t-idem3", command="approve")
        # After first approve: status = plan_approved

        # Manually change task status to simulate mid-flight change
        task = tasks_dao.get(db_conn, "t-idem3")
        tasks_dao.update(db_conn, "t-idem3", task.version, {"status": "in_progress", "updated_at": "2026-01-01T00:00:00Z"})
        db_conn.commit()

        # Second approve call — idempotent: must NOT re-transition
        rc = run_approve(project_dir, "t-idem3", command="approve")
        assert rc == 0

        task_after = tasks_dao.get(db_conn, "t-idem3")
        assert task_after.status == "in_progress", (
            "Second call must not overwrite status; row is duplicate so no transition"
        )

    def test_idempotency_key_is_deterministic(self) -> None:
        from superharness.commands.approve import _idempotency_key

        k1 = _idempotency_key("approve", "t-abc123")
        k2 = _idempotency_key("approve", "t-abc123")
        assert k1 == k2

    def test_approve_and_reject_have_separate_keys(self) -> None:
        from superharness.commands.approve import _idempotency_key

        k_approve = _idempotency_key("approve", "t-001")
        k_reject  = _idempotency_key("reject",  "t-001")
        assert k_approve != k_reject
