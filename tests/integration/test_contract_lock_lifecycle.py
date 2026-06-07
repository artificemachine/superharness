"""Integration tests for Iter 1: contract lock full lifecycle."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent


def _shux(args: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    base_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "superharness.cli"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=base_env,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "handoffs").mkdir()
    contract = f"""id: test-lock
created: 2026-01-01
tasks:
  - id: t-lock
    title: Lock test task
    owner: claude-code
    status: plan_proposed
    project_path: {tmp_path}
    acceptance_criteria:
      - must do X
      - must do Y
    tdd:
      red: write failing tests
      green: implement
      refactor: clean up
"""
    (sh / "contract.yaml").write_text(contract)
    _shux(["db", "ingest", "--project", str(tmp_path)], tmp_path)
    return tmp_path


def _get_task_from_db(project: Path, task_id: str) -> dict:
    """Read task directly from SQLite via shux context."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    conn = get_connection(str(project))
    init_db(conn)
    task = tasks_dao.get(conn, task_id)
    conn.close()
    if task is None:
        return {}
    return {
        "id": task.id,
        "status": task.status,
        "locked_contract": task.locked_contract,
        "contract_locked_at": task.contract_locked_at,
        "acceptance_criteria": task.acceptance_criteria,
    }


class TestContractLockLifecycle:
    def test_plan_approved_sets_locked_contract(self, project: Path):
        from superharness.engine import state_writer
        ok = state_writer.set_task_status(str(project), "t-lock", "plan_approved")
        assert ok, "status transition to plan_approved failed"
        task = _get_task_from_db(project, "t-lock")
        assert task["locked_contract"] is not None, "locked_contract should be set"
        assert task["contract_locked_at"] is not None, "contract_locked_at should be set"
        parsed = json.loads(task["locked_contract"])
        assert "must do X" in parsed["acceptance_criteria"]

    def test_locked_contract_is_immutable_after_plan_approved(self, project: Path):
        from superharness.engine import state_writer, tasks_dao
        from superharness.engine.db import get_connection, init_db
        from superharness.engine.state_errors import ContractLockError
        state_writer.set_task_status(str(project), "t-lock", "plan_approved")
        conn = get_connection(str(project))
        init_db(conn)
        task = tasks_dao.get(conn, "t-lock")
        assert task is not None
        with pytest.raises(ContractLockError):
            tasks_dao.update(conn, "t-lock", version=task.version,
                             changes={"acceptance_criteria": ["modified"]})
        conn.close()

    def test_review_handoff_includes_validation_contract(self, project: Path):
        from superharness.engine import state_writer, handoff_generator
        state_writer.set_task_status(str(project), "t-lock", "plan_approved")
        state_writer.set_task_status(str(project), "t-lock", "in_progress")
        state_writer.set_task_status(str(project), "t-lock", "report_ready")
        state_writer.set_task_status(str(project), "t-lock", "review_requested")
        handoff = handoff_generator.generate_handoff(str(project), "t-lock")
        assert "validation_contract" in handoff, "review handoff must include validation_contract"
        assert handoff["validation_contract"] is not None
        parsed = json.loads(handoff["validation_contract"])
        assert "acceptance_criteria" in parsed

    def test_non_review_handoff_has_no_validation_contract(self, project: Path):
        from superharness.engine import handoff_generator
        handoff = handoff_generator.generate_handoff(str(project), "t-lock")
        assert "validation_contract" not in handoff


# ── Iter 14 RED: contract lock must be released on review_failed → plan_proposed ─

def test_lock_released_on_revise(tmp_path):
    """Contract lock must be cleared when a task transitions review_failed → plan_proposed.

    RED: state_writer.set_task_status does not clear locked_contract/contract_locked_at
    on this transition. The agent cannot revise AC or TDD because the lock remains.
    GREEN: add a check: if status == 'plan_proposed' and prior == 'review_failed', clear lock.
    """
    import sqlite3
    from superharness.engine.db import get_connection, init_db
    from superharness.engine.state_writer import set_task_status
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    project = str(tmp_path / "proj")
    import os
    os.makedirs(os.path.join(project, ".superharness"))
    conn = get_connection(project)
    init_db(conn, project_dir=project)

    now = "2026-06-07T00:00:00Z"
    task_id = "t-lockrelease"
    conn.execute(
        "INSERT INTO tasks (id, title, status, owner, created_at, project_path) VALUES (?,?,?,?,?,?)",
        (task_id, "Lock release test", "todo", "claude-code", now, project),
    )
    conn.commit()

    # Advance through the lifecycle to review_failed
    for status in ("plan_proposed", "plan_approved", "in_progress", "report_ready", "review_requested", "review_failed"):
        ok = set_task_status(project_dir=project, task_id=task_id, status=status, force=True)
        assert ok, f"set_task_status({status!r}) returned False"

    # Verify the contract was locked at plan_approved
    row = conn.execute("SELECT contract_locked_at, locked_contract FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert row["contract_locked_at"] is not None, "contract should be locked after plan_approved"

    # Transition review_failed → plan_proposed (revise)
    ok = set_task_status(project_dir=project, task_id=task_id, status="plan_proposed")
    assert ok, "review_failed → plan_proposed must succeed"

    # The contract lock must now be cleared
    row = conn.execute("SELECT contract_locked_at, locked_contract FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert row["contract_locked_at"] is None, (
        f"contract_locked_at is still {row['contract_locked_at']!r} after review_failed→plan_proposed. "
        "The lock must be released so the agent can revise AC and TDD."
    )
    assert row["locked_contract"] is None, (
        "locked_contract still set after review_failed→plan_proposed. Must be cleared."
    )
    conn.close()
