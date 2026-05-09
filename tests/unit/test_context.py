"""Tests for superharness context command (TDD — all RED first, then implement)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.helpers import REPO_ROOT, seed_sqlite_from_yaml


def _run_cmd(args: list[str], env: dict | None = None):
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(REPO_ROOT / "src")
    if env:
        merged.update(env)
    cmd = [sys.executable, "-m", "superharness.commands.context"] + args
    return subprocess.run(cmd, cwd=str(REPO_ROOT), text=True, capture_output=True, env=merged, check=False)


def _make_contract(harness: Path, task_id: str = "feat-001", status: str = "in_progress") -> None:
    (harness / "contract.yaml").write_text(
        f"id: test-contract\ntasks:\n"
        f"  - id: {task_id}\n"
        f"    title: Build feature one\n"
        f"    owner: claude-code\n"
        f"    status: {status}\n"
    )


def _setup_project(tmp_path: Path, task_id: str = "feat-001", status: str = "in_progress") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True)
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    (harness / "ledger.md").write_text("# Ledger\n\n")
    _make_contract(harness, task_id, status)
    seed_sqlite_from_yaml(project)
    return project


class TestContextCommand:
    def test_context_shows_task_status(self, tmp_path):
        """Context output must include the task status."""
        project = _setup_project(tmp_path, status="in_progress")
        result = _run_cmd(["--project", str(project), "feat-001"])
        assert result.returncode == 0, result.stderr
        assert "in_progress" in result.stdout

    def test_context_shows_last_handoff(self, tmp_path):
        """Context output must include outcome and context fields from the last handoff."""
        project = _setup_project(tmp_path)
        handoff = project / ".superharness" / "handoffs" / "2026-03-14-feat-001-report.yaml"
        handoff.write_text(
            "task: feat-001\nphase: report\nstatus: report_ready\n"
            "from: claude-code\nto: owner\ndate: 2026-03-14T10:00:00Z\n"
            "outcome: Fixed race condition in inbox dispatch\n"
            "context: |\n  Next session must know - lock directory approach was chosen.\n"
        )
        result = _run_cmd(["--project", str(project), "feat-001"])
        assert result.returncode == 0, result.stderr
        assert "race condition" in result.stdout.lower()
        assert "lock directory" in result.stdout.lower()

    def test_context_shows_decisions(self, tmp_path):
        """Context output must include entries from decisions.yaml."""
        project = _setup_project(tmp_path)
        (project / ".superharness" / "decisions.yaml").write_text(
            "decisions:\n"
            "  - date: '2026-03-10'\n"
            "    task: feat-001\n"
            "    decision: use lock directory approach for feat-001\n"
        )
        result = _run_cmd(["--project", str(project), "feat-001"])
        assert result.returncode == 0, result.stderr
        assert "lock directory" in result.stdout.lower()

    def test_context_shows_failures(self, tmp_path):
        """Context output must include entries from failures.yaml."""
        project = _setup_project(tmp_path)
        (project / ".superharness" / "failures.yaml").write_text(
            "failures:\n"
            "  - date: '2026-03-09'\n"
            "    task: feat-001\n"
            "    failure: atomic rename breaks on NFS mounts for feat-001\n"
        )
        result = _run_cmd(["--project", str(project), "feat-001"])
        assert result.returncode == 0, result.stderr
        assert "atomic rename" in result.stdout.lower()

    def test_context_shows_blocker_failures(self, tmp_path):
        """Context output must include entries from failures.yaml for blocking tasks."""
        project = _setup_project(tmp_path)
        # feat-002 is blocked by feat-001
        (project / ".superharness" / "contract.yaml").write_text(
            "id: test-contract\ntasks:\n"
            "  - id: feat-001\n"
            "    status: done\n"
            "  - id: feat-002\n"
            "    blocked_by: feat-001\n"
            "    status: in_progress\n"
        )
        (project / ".superharness" / "failures.yaml").write_text(
            "failures:\n"
            "  - date: '2026-03-09'\n"
            "    task: feat-001\n"
            "    failure: blocker failure context\n"
            "  - date: '2026-03-10'\n"
            "    task: other-task\n"
            "    failure: unrelated failure\n"
        )
        result = _run_cmd(["--project", str(project), "feat-002"])
        assert result.returncode == 0, result.stderr
        assert "blocker failure context" in result.stdout.lower()
        assert "unrelated failure" not in result.stdout.lower()
        assert "[feat-001]" in result.stdout  # Should show which task the failure belonged to if not current

    def test_context_shows_ledger_entries(self, tmp_path):
        """Context output must include recent ledger lines mentioning the task."""
        project = _setup_project(tmp_path)
        (project / ".superharness" / "ledger.md").write_text(
            "# Ledger\n\n"
            "- 2026-03-14T09:12Z — claude-code — IN_PROGRESS: feat-001\n"
            "- 2026-03-14T11:44Z — claude-code — REPORT: feat-001\n"
        )
        result = _run_cmd(["--project", str(project), "feat-001"])
        assert result.returncode == 0, result.stderr
        assert "IN_PROGRESS" in result.stdout or "REPORT" in result.stdout

    def test_context_auto_selects_active_task(self, tmp_path):
        """When no task-id given, context must auto-select the in_progress task."""
        project = _setup_project(tmp_path, task_id="auto-task", status="in_progress")
        result = _run_cmd(["--project", str(project)])
        assert result.returncode == 0, result.stderr
        assert "auto-task" in result.stdout

    def test_context_unknown_task_exits_1(self, tmp_path):
        """Context must exit non-zero for a task-id that doesn't exist."""
        project = _setup_project(tmp_path)
        result = _run_cmd(["--project", str(project), "nonexistent-task-xyz"])
        assert result.returncode != 0

    def test_context_no_git_repo_skips_git(self, tmp_path):
        """In a non-git directory, context must not crash and must omit the git section."""
        non_git = tmp_path / "no_git_proj"
        non_git.mkdir()
        harness = non_git / ".superharness"
        (harness / "handoffs").mkdir(parents=True)
        (harness / "decisions.yaml").write_text("decisions: []\n")
        (harness / "failures.yaml").write_text("failures: []\n")
        (harness / "ledger.md").write_text("# Ledger\n\n")
        (harness / "contract.yaml").write_text(
            "id: test\ntasks:\n  - id: t1\n    title: T\n    owner: claude-code\n    status: in_progress\n"
        )
        result = _run_cmd(["--project", str(non_git), "t1"])
        assert result.returncode == 0, result.stderr
        # Should not show a git error — either omits the section or shows no crash
        assert "Traceback" not in result.stdout
        assert "Traceback" not in result.stderr
