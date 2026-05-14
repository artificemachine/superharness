"""RED tests for phase-4 YAML→SQLite cleanup.

Covers:
- close_task works without contract.yaml (reads/writes SQLite only)
- preflight _check_prior_failures reads from SQLite not failures.yaml
- contract_validate works without contract.yaml
- state_reader legacy YAML functions removed
- init_project does not try to patch contract.yaml
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine import tasks_dao, failures_dao


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mk_sqlite_project(tmp_path: Path) -> Path:
    """Create a minimal project with only SQLite — no YAML state files."""
    project = tmp_path / "proj"
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True)
    (harness / "ledger.md").write_text("# Ledger\n", encoding="utf-8")
    conn = get_connection(str(project))
    init_db(conn)
    conn.commit()
    conn.close()
    return project


def _seed_task(project: Path, task_id: str, status: str, verified: bool = False,
               owner: str = "claude-code") -> None:
    """Insert a task row into project SQLite."""
    now = _now()
    conn = get_connection(str(project))
    init_db(conn)
    tasks_dao.upsert(conn, tasks_dao.TaskRow(
        id=task_id, title=f"Task {task_id}", owner=owner,
        status=status, effort="small", project_path=str(project),
        development_method=None, acceptance_criteria=None,
        test_types=None, out_of_scope=None, definition_of_done=None,
        context=None, tdd=None, version=1, created_at=now,
        blocked_by=None, parent_id=None,
        verified=verified,
    ))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# close.py — reads task from SQLite, writes status to SQLite
# ---------------------------------------------------------------------------

class TestCloseTaskSQLite:
    def test_close_task_accepts_project_dir_not_contract_file(self, tmp_path):
        """close_task signature takes project_dir as first argument."""
        from superharness.commands.close import close_task
        import inspect
        sig = inspect.signature(close_task)
        first_param = list(sig.parameters.keys())[0]
        assert first_param == "project_dir", (
            f"Expected first param 'project_dir', got '{first_param}'. "
            "close_task signature must change from contract_file to project_dir."
        )

    def test_close_task_works_without_contract_yaml(self, tmp_path):
        """close_task must succeed even when contract.yaml does not exist."""
        from superharness.commands.close import close_task
        project = _mk_sqlite_project(tmp_path)
        _seed_task(project, "my-task", "report_ready", verified=True)
        assert not (project / ".superharness" / "contract.yaml").exists()

        rc = close_task(str(project), "my-task", "claude-code", "done", skip_verify=True, force=True)
        assert rc == 0, "close_task should succeed with SQLite-only project"

    def test_close_task_reads_task_status_from_sqlite(self, tmp_path):
        """close_task correctly reads task status from SQLite (not YAML)."""
        from superharness.commands.close import close_task
        project = _mk_sqlite_project(tmp_path)
        # Task in SQLite with report_ready
        _seed_task(project, "t1", "report_ready", verified=True)

        rc = close_task(str(project), "t1", "claude-code", "done", skip_verify=True)
        assert rc == 0

    def test_close_task_returns_1_for_missing_task(self, tmp_path):
        """close_task returns 1 when task_id is not found in SQLite."""
        from superharness.commands.close import close_task
        project = _mk_sqlite_project(tmp_path)

        rc = close_task(str(project), "nonexistent-task", "claude-code", "done", force=True)
        assert rc == 1, "Should return 1 when task not found in SQLite"

    def test_close_task_writes_done_status_to_sqlite(self, tmp_path):
        """After close_task succeeds, the task row in SQLite has status='done'."""
        from superharness.commands.close import close_task
        project = _mk_sqlite_project(tmp_path)
        _seed_task(project, "close-me", "report_ready", verified=True)

        rc = close_task(str(project), "close-me", "claude-code", "finished", skip_verify=True)
        assert rc == 0

        conn = get_connection(str(project))
        init_db(conn)
        row = tasks_dao.get(conn, "close-me")
        conn.close()
        assert row is not None
        assert row.status == "done"

    def test_close_task_owner_gate_enforced_from_sqlite(self, tmp_path):
        """close_task enforces owner gate using owner from SQLite, not YAML."""
        from superharness.commands.close import close_task
        project = _mk_sqlite_project(tmp_path)
        _seed_task(project, "owned-task", "report_ready", verified=True, owner="codex-cli")

        rc = close_task(str(project), "owned-task", "claude-code", "done", skip_verify=True)
        # claude-code is not the owner — should be forbidden
        assert rc == 1, "Should refuse wrong actor per SQLite owner field"


# ---------------------------------------------------------------------------
# preflight.py — _check_prior_failures reads from SQLite
# ---------------------------------------------------------------------------

class TestPreflightPriorFailures:
    def test_prior_failures_from_sqlite_not_yaml(self, tmp_path):
        """_check_prior_failures returns results from SQLite, not failures.yaml."""
        from superharness.engine.preflight import _check_prior_failures

        project = _mk_sqlite_project(tmp_path)
        now = _now()
        conn = get_connection(str(project))
        init_db(conn)
        failures_dao.record(conn, task_id="task-x", agent="claude-code",
                            pattern="import error", error_snippet="ModuleNotFoundError", now=now)
        conn.commit()
        conn.close()

        # No failures.yaml exists
        assert not (project / ".superharness" / "failures.yaml").exists()

        checks = _check_prior_failures(str(project), "task-x")
        assert len(checks) == 1
        assert "prior_failures" in checks[0].id or "failure" in checks[0].id.lower()

    def test_prior_failures_empty_when_no_sqlite_records(self, tmp_path):
        """_check_prior_failures returns [] when SQLite has no failures for this task."""
        from superharness.engine.preflight import _check_prior_failures

        project = _mk_sqlite_project(tmp_path)
        checks = _check_prior_failures(str(project), "task-nobody")
        assert checks == []

    def test_prior_failures_does_not_require_failures_yaml(self, tmp_path):
        """_check_prior_failures must not raise when failures.yaml is absent."""
        from superharness.engine.preflight import _check_prior_failures

        project = _mk_sqlite_project(tmp_path)
        # Ensure failures.yaml is absent
        failures_yaml = project / ".superharness" / "failures.yaml"
        assert not failures_yaml.exists()

        # Should not raise
        checks = _check_prior_failures(str(project), "no-task")
        assert isinstance(checks, list)


# ---------------------------------------------------------------------------
# contract_validate.py — uses SQLite not contract.yaml
# ---------------------------------------------------------------------------

class TestContractValidateSQLite:
    def test_validate_works_without_contract_yaml(self, tmp_path):
        """contract_validate should succeed (or fail with task errors) without contract.yaml."""
        from superharness.commands.contract_validate import validate_contract

        project = _mk_sqlite_project(tmp_path)
        _seed_task(project, "v-task", "done", verified=True, owner="claude-code")
        assert not (project / ".superharness" / "contract.yaml").exists()

        # Should not raise FileNotFoundError
        result = validate_contract(str(project))
        assert result is not None  # should return some result object or int

    def test_validate_reads_tasks_from_sqlite(self, tmp_path):
        """validate_contract reports tasks from SQLite."""
        from superharness.commands.contract_validate import validate_contract

        project = _mk_sqlite_project(tmp_path)
        _seed_task(project, "val-task", "in_progress", owner="claude-code")

        result = validate_contract(str(project))
        # Result should be a dict or object with task info — not None / not a crash
        assert result is not None


# ---------------------------------------------------------------------------
# state_reader.py — legacy YAML functions removed
# ---------------------------------------------------------------------------

class TestStateReaderLegacyRemoved:
    def test_inbox_from_yaml_removed(self):
        """_inbox_from_yaml must not exist in state_reader."""
        from superharness.engine import state_reader
        assert not hasattr(state_reader, "_inbox_from_yaml"), (
            "_inbox_from_yaml is a legacy YAML function that should be removed"
        )

    def test_tasks_from_yaml_removed(self):
        """_tasks_from_yaml must not exist in state_reader."""
        from superharness.engine import state_reader
        assert not hasattr(state_reader, "_tasks_from_yaml"), (
            "_tasks_from_yaml is a legacy YAML function that should be removed"
        )

    def test_contract_yaml_fn_removed(self):
        """_contract_yaml must not exist in state_reader."""
        from superharness.engine import state_reader
        assert not hasattr(state_reader, "_contract_yaml"), (
            "_contract_yaml is a legacy YAML function that should be removed"
        )

    def test_handoffs_from_yaml_removed(self):
        """_handoffs_from_yaml must not exist in state_reader."""
        from superharness.engine import state_reader
        assert not hasattr(state_reader, "_handoffs_from_yaml"), (
            "_handoffs_from_yaml is a legacy YAML function that should be removed"
        )

    def test_get_tasks_returns_list(self, tmp_path):
        """get_tasks still works after legacy functions are removed."""
        from superharness.engine import state_reader

        project = _mk_sqlite_project(tmp_path)
        _seed_task(project, "sr-task", "done", verified=True)

        tasks = state_reader.get_tasks(str(project))
        assert isinstance(tasks, list)
        assert any(t.get("id") == "sr-task" for t in tasks if isinstance(t, dict))


# ---------------------------------------------------------------------------
# init_project.py — no dead contract.yaml patch block
# ---------------------------------------------------------------------------

class TestInitProjectNoPatch:
    def test_init_does_not_write_contract_yaml_on_init(self, tmp_path, monkeypatch):
        """init command must not create contract.yaml in a fresh project."""
        import sys
        # Point to a fresh directory
        monkeypatch.chdir(str(tmp_path))
        monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(""))

        from superharness.commands.init_project import main

        # Run non-interactive init with --skip-hooks to avoid side-effects
        main(["--skip-hooks"])

        harness = tmp_path / ".superharness"
        assert harness.is_dir()
        # contract.yaml must NOT be created
        assert not (harness / "contract.yaml").exists(), (
            "init must not create contract.yaml — state lives in SQLite"
        )

    def test_dry_run_output_does_not_promise_contract_yaml_as_state(self, tmp_path, capsys, monkeypatch):
        """dry-run output should not list contract.yaml as a primary state artifact."""
        import sys
        monkeypatch.chdir(str(tmp_path))

        from superharness.commands.init_project import main
        main(["--dry-run", "--skip-hooks"])

        captured = capsys.readouterr()
        # The dry-run may mention it historically, but must not claim it's the state source
        # Specifically, it should not say "contract.yaml ← edit this with your first task"
        assert "edit this with your first task" not in captured.out
