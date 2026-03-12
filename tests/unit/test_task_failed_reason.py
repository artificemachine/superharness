from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.helpers import run_bash


def _make_project(tmp_path: Path, task_id: str, owner: str, status: str = "in_progress") -> Path:
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
        f"    project_path: \"{project}\"\n"
        f"decisions: []\n"
        f"failures: []\n"
    )
    return project


def _task_sh(repo_root: Path, project: Path, *args: str) -> subprocess.CompletedProcess:
    return run_bash(
        repo_root / "scripts" / "task.sh",
        cwd=repo_root,
        args=["status", "--project", str(project)] + list(args),
    )


@pytest.mark.parametrize(
    ("status", "summary", "reason", "expect_ok", "needle"),
    [
        ("todo", "", "", False, "summary"),
        ("in_progress", "", "", False, "summary"),
        ("pending_user_approval", "", "", False, "summary"),
        ("done", "", "", False, "summary"),
        ("failed", "", "", False, "reason"),
        ("stopped", "", "", False, "reason"),
        ("todo", "queued", "", True, "status: todo"),
        ("in_progress", "working", "", True, "status: in_progress"),
        ("pending_user_approval", "awaiting approval", "", True, "status: pending_user_approval"),
        ("done", "completed", "", True, "status: done"),
        ("failed", "", "runtime_failure", True, "status: failed"),
        ("stopped", "", "operator_halt", True, "status: stopped"),
    ],
)
def test_task_status_requirements_matrix(repo_root, tmp_path, status, summary, reason, expect_ok, needle) -> None:
    project = _make_project(tmp_path, f"matrix-{status}", "claude-code")
    args = [
        "--id",
        f"matrix-{status}",
        "--status",
        status,
        "--actor",
        "claude-code",
    ]
    if summary:
        args.extend(["--summary", summary])
    if reason:
        args.extend(["--reason", reason])

    result = _task_sh(repo_root, project, *args)
    if expect_ok:
        assert result.returncode == 0, result.stderr
        contract_text = (project / ".superharness" / "contract.yaml").read_text()
        assert needle in contract_text
    else:
        assert result.returncode != 0
        assert needle in result.stderr


def test_failed_status_records_reason(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task", "claude-code")

    result = _task_sh(
        repo_root, project,
        "--id", "my-task",
        "--status", "failed",
        "--actor", "claude-code",
        "--reason", "orphaned_no_output",
    )

    assert result.returncode == 0, result.stderr

    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "status: failed" in contract_text
    assert "stopped_reason: orphaned_no_output" in contract_text
    assert "stopped_at:" in contract_text


def test_failed_status_requires_reason(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task2", "claude-code")

    result = _task_sh(
        repo_root, project,
        "--id", "my-task2",
        "--status", "failed",
        "--actor", "claude-code",
    )

    assert result.returncode != 0
    assert "reason" in result.stderr


def test_failed_status_clears_reason_on_reopen(repo_root, tmp_path) -> None:
    """Resetting a failed task back to todo removes the failure fields."""
    project = _make_project(tmp_path, "my-task3", "claude-code")

    _task_sh(
        repo_root, project,
        "--id", "my-task3",
        "--status", "failed",
        "--actor", "claude-code",
        "--reason", "some_reason",
    )

    result = _task_sh(
        repo_root, project,
        "--id", "my-task3",
        "--status", "todo",
        "--actor", "claude-code",
        "--summary", "Reopened after false alarm.",
    )
    assert result.returncode == 0, result.stderr

    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "status: todo" in contract_text
    assert "stopped_reason" not in contract_text
    assert "stopped_at" not in contract_text


def test_stopped_status_records_reason(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task-stop", "codex-cli")

    result = _task_sh(
        repo_root, project,
        "--id", "my-task-stop",
        "--status", "stopped",
        "--actor", "codex-cli",
        "--reason", "operator_manually_halted",
    )

    assert result.returncode == 0, result.stderr

    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "status: stopped" in contract_text
    assert "stopped_reason: operator_manually_halted" in contract_text
    assert "stopped_at:" in contract_text


def test_stopped_status_requires_reason(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task-stop2", "codex-cli")

    result = _task_sh(
        repo_root, project,
        "--id", "my-task-stop2",
        "--status", "stopped",
        "--actor", "codex-cli",
    )

    assert result.returncode != 0
    assert "reason" in result.stderr


def test_done_status_records_summary(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task-done", "claude-code")

    result = _task_sh(
        repo_root, project,
        "--id", "my-task-done",
        "--status", "done",
        "--actor", "claude-code",
        "--summary", "Split README into user-guide and architecture docs. PR merged.",
    )

    assert result.returncode == 0, result.stderr
    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "status: done" in contract_text
    assert "Split README" in contract_text


def test_in_progress_status_records_summary(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task-wip", "claude-code", status="todo")

    result = _task_sh(
        repo_root, project,
        "--id", "my-task-wip",
        "--status", "in_progress",
        "--actor", "claude-code",
        "--summary", "Started refactor, blocked on missing fixture.",
    )

    assert result.returncode == 0, result.stderr
    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "status: in_progress" in contract_text
    assert "blocked on missing fixture" in contract_text


def test_summary_is_required_for_done(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task-nosummary", "claude-code")

    result = _task_sh(
        repo_root, project,
        "--id", "my-task-nosummary",
        "--status", "done",
        "--actor", "claude-code",
    )

    assert result.returncode != 0
    assert "summary" in result.stderr


def test_pending_user_approval_status_requires_summary(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task-approval-summary", "claude-code")

    result = _task_sh(
        repo_root, project,
        "--id", "my-task-approval-summary",
        "--status", "pending_user_approval",
        "--actor", "claude-code",
    )

    assert result.returncode != 0
    assert "summary" in result.stderr


def test_pending_user_approval_status_records_summary(repo_root, tmp_path) -> None:
    project = _make_project(tmp_path, "my-task-approval", "claude-code")

    result = _task_sh(
        repo_root, project,
        "--id", "my-task-approval",
        "--status", "pending_user_approval",
        "--actor", "claude-code",
        "--summary", "Consensus reached, awaiting user approval.",
    )

    assert result.returncode == 0, result.stderr
    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "status: pending_user_approval" in contract_text
    assert "awaiting user approval" in contract_text


def test_deadline_check_sets_contract_failed_reason(repo_root, tmp_path) -> None:
    """inbox-deadline-check.sh must also set failed status + reason on the contract task."""
    project = tmp_path / "proj-deadline-contract"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    (harness / "handoffs").mkdir()
    (harness / "failures.yaml").write_text("failures: []\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "ledger.md").write_text("# Ledger\n\nAppend-only.\n")

    (harness / "contract.yaml").write_text(
        f"id: test-contract\n"
        f"tasks:\n"
        f"  - id: slow-task\n"
        f"    title: Slow task\n"
        f"    status: in_progress\n"
        f"    owner: claude-code\n"
        f"    deadline_minutes: 1\n"
        f"    project_path: \"{project}\"\n"
        f"decisions: []\n"
        f"failures: []\n"
    )
    (harness / "inbox.yaml").write_text(
        f"# Delegation inbox\n"
        f"---\n"
        f"- id: inbox-slow-task\n"
        f"  to: claude-code\n"
        f"  task: slow-task\n"
        f"  project: \"{project}\"\n"
        f"  status: launched\n"
        f"  launched_at: 2026-01-01T00:00:00Z\n"
        f"  priority: 1\n"
        f"  retry_count: 1\n"
        f"  max_retries: 3\n"
    )

    script = repo_root / "scripts" / "inbox-deadline-check.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])
    assert result.returncode == 0, result.stderr
    assert "exceeded=1" in result.stdout

    contract_text = (harness / "contract.yaml").read_text()
    assert "status: failed" in contract_text
    assert "deadline_exceeded" in contract_text
    assert "stopped_at:" in contract_text
