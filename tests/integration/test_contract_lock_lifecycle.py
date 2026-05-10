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
