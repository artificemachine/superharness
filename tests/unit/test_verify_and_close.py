"""Tests for superharness verify and close commands."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.helpers import REPO_ROOT


def _run_cmd(module: str, cwd, args: list[str], env: dict | None = None):
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(REPO_ROOT / "src")
    if env:
        merged.update(env)
    cmd = [sys.executable, "-m", module] + args
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=merged, check=False)


def _setup_project(tmp_path: Path, task_status: str = "report_ready", verified: bool = False) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")

    task_yaml = (
        f"id: test-contract\n"
        f"created: '2026-01-01T00:00:00Z'\n"
        f"created_by: owner\n"
        f"status: active\n"
        f"tasks:\n"
        f"  - id: feat-001\n"
        f"    title: Build feature one\n"
        f"    owner: claude-code\n"
        f"    status: {task_status}\n"
        f"    project_path: '{project.as_posix()}'\n"
    )
    if verified:
        task_yaml += (
            "    verified: true\n"
            "    verified_at: '2026-03-15T00:00:00Z'\n"
            "    verified_by: claude-code\n"
        )

    (harness / "contract.yaml").write_text(task_yaml)
    (harness / "ledger.md").write_text("# Ledger\n\n")

    # Seed SQLite so read_contract (sqlite_only=True) finds the task.
    from superharness.engine.db import get_connection, init_db, transaction
    from superharness.engine.contract_io import _task_row_from_dict
    from superharness.engine import tasks_dao
    task_dict: dict = {
        "id": "feat-001", "title": "Build feature one", "owner": "claude-code",
        "status": task_status, "project_path": project.as_posix(),
    }
    if verified:
        task_dict["verified"] = True
        task_dict["verified_at"] = "2026-03-15T00:00:00Z"
        task_dict["verified_by"] = "claude-code"
    conn = get_connection(str(project))
    init_db(conn)
    with transaction(conn):
        tasks_dao.upsert(conn, _task_row_from_dict(task_dict, str(project), "2026-01-01T00:00:00Z"))
    conn.commit()
    conn.close()
    seed_sqlite_from_yaml(project)

    return project


def _get_task_sqlite(project: Path, task_id: str) -> dict:
    """Read a task directly from SQLite (used in assertions since sqlite_only skips YAML writes)."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    conn = get_connection(str(project))
    init_db(conn)
    row = tasks_dao.get(conn, task_id)
    conn.close()
    if row is None:
        raise KeyError(f"task '{task_id}' not found in SQLite")
    from dataclasses import asdict
    return asdict(row)


# ---------------------------------------------------------------------------
# Verify command tests
# ---------------------------------------------------------------------------


class TestVerify:
    def test_verify_pass_sets_verified_true(self, tmp_path):
        project = _setup_project(tmp_path)
        result = _run_cmd(
            "superharness.commands.verify", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--method", "pytest all green", "--result", "pass", "--actor", "claude-code"],
        )
        assert result.returncode == 0, result.stderr
        assert "PASS" in result.stdout

        # In sqlite_only mode write_contract skips YAML; read from SQLite instead.
        task = _get_task_sqlite(project, "feat-001")
        assert task["verified"] is True
        assert task["verified_by"] == "claude-code"
        assert task["verified_at"]

    def test_verify_fail_sets_verified_false(self, tmp_path):
        project = _setup_project(tmp_path)
        result = _run_cmd(
            "superharness.commands.verify", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--method", "e2e test failed", "--result", "fail", "--actor", "claude-code"],
        )
        assert result.returncode == 0, result.stderr
        assert "FAIL" in result.stdout

        task = _get_task_sqlite(project, "feat-001")
        assert task["verified"] is False

    def test_verify_appends_ledger_entry(self, tmp_path):
        project = _setup_project(tmp_path)
        _run_cmd(
            "superharness.commands.verify", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--method", "smoke test", "--result", "pass", "--actor", "claude-code"],
        )
        ledger = (project / ".superharness" / "ledger.md").read_text()
        assert "VERIFY PASS" in ledger
        assert "feat-001" in ledger
        assert "smoke test" in ledger

    def test_verify_invalid_result_rejected(self, tmp_path):
        project = _setup_project(tmp_path)
        result = _run_cmd(
            "superharness.commands.verify", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--method", "test", "--result", "maybe", "--actor", "claude-code"],
        )
        assert result.returncode != 0

    def test_verify_unknown_task_fails(self, tmp_path):
        project = _setup_project(tmp_path)
        result = _run_cmd(
            "superharness.commands.verify", REPO_ROOT,
            ["--project", str(project), "--id", "nonexistent",
             "--method", "test", "--result", "pass", "--actor", "claude-code"],
        )
        assert result.returncode != 0
        assert "not found" in result.stderr


# ---------------------------------------------------------------------------
# Close command tests
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_verified_task_succeeds(self, tmp_path):
        project = _setup_project(tmp_path, task_status="report_ready", verified=True)
        result = _run_cmd(
            "superharness.commands.close", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--actor", "claude-code", "--summary", "All done"],
        )
        assert result.returncode == 0, result.stderr
        assert "Closed task 'feat-001'" in result.stdout

        task = _get_task_sqlite(project, "feat-001")
        assert task["status"] == "done"

    def test_close_unverified_task_fails(self, tmp_path):
        project = _setup_project(tmp_path, task_status="report_ready", verified=False)
        result = _run_cmd(
            "superharness.commands.close", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--actor", "claude-code", "--summary", "Done"],
        )
        assert result.returncode == 1
        assert "not verified" in result.stderr
        assert "superharness verify" in result.stderr

    def test_close_skip_verify_bypasses_gate(self, tmp_path):
        project = _setup_project(tmp_path, task_status="report_ready", verified=False)
        result = _run_cmd(
            "superharness.commands.close", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--actor", "claude-code", "--summary", "Emergency close",
             "--skip-verify"],
        )
        assert result.returncode == 0, result.stderr
        assert "Closed task" in result.stdout

    def test_close_appends_ledger_entry(self, tmp_path):
        project = _setup_project(tmp_path, task_status="report_ready", verified=True)
        _run_cmd(
            "superharness.commands.close", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--actor", "claude-code", "--summary", "Feature complete"],
        )
        ledger = (project / ".superharness" / "ledger.md").read_text()
        assert "CLOSE" in ledger
        assert "feat-001" in ledger

    def test_close_writes_handoff_yaml(self, tmp_path):
        project = _setup_project(tmp_path, task_status="report_ready", verified=True)
        _run_cmd(
            "superharness.commands.close", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--actor", "claude-code", "--summary", "Shipped"],
        )
        handoff = project / ".superharness" / "handoffs" / "feat-001-to-owner.yaml"
        assert handoff.exists()
        import yaml
        with open(handoff) as f:
            data = yaml.safe_load(f)
        assert data["task"] == "feat-001"
        assert data["status"] == "done"

    def test_close_wrong_actor_fails(self, tmp_path):
        project = _setup_project(tmp_path, task_status="report_ready", verified=True)
        result = _run_cmd(
            "superharness.commands.close", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--actor", "codex-cli", "--summary", "Done"],
        )
        assert result.returncode != 0
        assert "forbidden" in result.stderr

    def test_close_unknown_task_fails(self, tmp_path):
        project = _setup_project(tmp_path)
        result = _run_cmd(
            "superharness.commands.close", REPO_ROOT,
            ["--project", str(project), "--id", "nonexistent",
             "--actor", "claude-code", "--summary", "Done"],
        )
        assert result.returncode != 0
        assert "not found" in result.stderr

    def test_close_writes_context_to_handoff(self, tmp_path):
        """--context value must appear in handoff YAML."""
        project = _setup_project(tmp_path, task_status="report_ready", verified=True)
        ctx_msg = "Next session must know: use advisory lock, not flock."
        result = _run_cmd(
            "superharness.commands.close", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--actor", "claude-code", "--summary", "Done",
             "--context", ctx_msg],
        )
        assert result.returncode == 0, result.stderr
        handoff = project / ".superharness" / "handoffs" / "feat-001-to-owner.yaml"
        assert handoff.exists()
        import yaml
        with open(handoff) as f:
            data = yaml.safe_load(f)
        assert "context" in data
        assert ctx_msg in data["context"]

    def test_close_without_context_still_works(self, tmp_path):
        """Closing without --context must succeed and omit context field from handoff."""
        project = _setup_project(tmp_path, task_status="report_ready", verified=True)
        result = _run_cmd(
            "superharness.commands.close", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--actor", "claude-code", "--summary", "Done"],
        )
        assert result.returncode == 0, result.stderr
        handoff = project / ".superharness" / "handoffs" / "feat-001-to-owner.yaml"
        assert handoff.exists()
        import yaml
        with open(handoff) as f:
            data = yaml.safe_load(f)
        assert "context" not in data or not data["context"]


# ---------------------------------------------------------------------------
# Verify → Close integration
# ---------------------------------------------------------------------------


class TestVerifyThenClose:
    def test_verify_then_close_full_flow(self, tmp_path):
        project = _setup_project(tmp_path, task_status="report_ready")

        # Close fails before verify
        r1 = _run_cmd(
            "superharness.commands.close", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--actor", "claude-code", "--summary", "Done"],
        )
        assert r1.returncode == 1

        # Verify pass
        r2 = _run_cmd(
            "superharness.commands.verify", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--method", "e2e test pass", "--result", "pass", "--actor", "claude-code"],
        )
        assert r2.returncode == 0

        # Close succeeds after verify
        r3 = _run_cmd(
            "superharness.commands.close", REPO_ROOT,
            ["--project", str(project), "--id", "feat-001",
             "--actor", "claude-code", "--summary", "Feature shipped"],
        )
        assert r3.returncode == 0

        task = _get_task_sqlite(project, "feat-001")
        assert task["status"] == "done"
        assert task["verified"] is True
