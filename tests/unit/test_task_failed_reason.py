from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.helpers import run_bash
import sys

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _make_project(
    tmp_path: Path, task_id: str, owner: str, status: str = "in_progress"
) -> Path:
    project = tmp_path / f"proj-{task_id}"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text(
        f"id: test-contract\n"
        f"tasks:\n"
        f"  - id: {task_id}\n"
        f"    title: Test task\n"
        f"    status: {status}\n"
        f"    owner: {owner}\n"
        f'    project_path: "{project}"\n'
        f"decisions: []\n"
        f"failures: []\n"
    )
    from tests.helpers import seed_sqlite_from_yaml

    seed_sqlite_from_yaml(project)
    return project


def _task_sh(repo_root: Path, project: Path, *args: str) -> subprocess.CompletedProcess:
    return run_bash(
        repo_root / "src" / "superharness" / "scripts" / "task.sh",
        cwd=repo_root,
        args=["status", "--project", str(project)] + list(args),
    )






def test_failed_status_requires_reason(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task2", "claude-code")

    result = _task_sh(
        repo_root,
        project,
        "--id",
        "my-task2",
        "--status",
        "failed",
        "--actor",
        "claude-code",
    )

    assert result.returncode != 0
    assert "reason" in result.stderr






def test_stopped_status_requires_reason(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task-stop2", "codex-cli")

    result = _task_sh(
        repo_root,
        project,
        "--id",
        "my-task-stop2",
        "--status",
        "stopped",
        "--actor",
        "codex-cli",
    )

    assert result.returncode != 0
    assert "reason" in result.stderr






def test_summary_is_required_for_done(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task-nosummary", "claude-code")

    result = _task_sh(
        repo_root,
        project,
        "--id",
        "my-task-nosummary",
        "--status",
        "done",
        "--actor",
        "claude-code",
    )

    assert result.returncode != 0
    assert "summary" in result.stderr


def test_pending_user_approval_status_requires_summary(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task-approval-summary", "claude-code")

    result = _task_sh(
        repo_root,
        project,
        "--id",
        "my-task-approval-summary",
        "--status",
        "pending_user_approval",
        "--actor",
        "claude-code",
    )

    assert result.returncode != 0
    assert "summary" in result.stderr




