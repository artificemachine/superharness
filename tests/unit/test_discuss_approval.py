from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT, run_bash, seed_sqlite_from_yaml

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")



def _run_discuss_py(cwd, args: list[str] | None = None):
    """Run discuss Python module."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.commands.discuss"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: c1",
                "tasks:",
                "  - id: approval-task",
                "    title: Needs approval",
                "    owner: codex-cli",
                "    status: pending_user_approval",
                f"    project_path: '{project.as_posix()}'" ,
                "  - id: claude-task",
                "    title: Claude task",
                "    owner: claude-code",
                "    status: todo",
                f"    project_path: '{project.as_posix()}'" ,
            ]
        )
        + "\n"
    )
    (harness / "inbox.yaml").write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale|paused",
                "",
                "- id: approval-item",
                "  to: codex-cli",
                "  task: approval-task",
                f"  project: {project}",
                "  status: paused",
                "  pause_reason: awaiting_user_approval",
                "  priority: 1",
                "  retry_count: 0",
                "  max_retries: 3",
            ]
        )
        + "\n"
    )
    (harness / "handoffs" / "2026-03-11-approval-task.yaml").write_text(
        "\n".join(
            [
                "task: approval-task",
                "to: codex-cli",
                "date: 2026-03-11",
                "status: pending_user_approval",
                "approval_gate:",
                "  required: true",
                "  approved_by_user: false",
                "  approved_at: null",
                "markdown_report: .superharness/handoffs/2026-03-11-approval-task.md",
            ]
        )
        + "\n"
    )
    seed_sqlite_from_yaml(project)
    return project


def _setup_project_without_paused_item(tmp_path: Path) -> Path:
    project = tmp_path / "proj_no_paused"
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: c1",
                "tasks:",
                "  - id: approval-task",
                "    title: Needs approval",
                "    owner: codex-cli",
                "    status: pending_user_approval",
                f"    project_path: '{project.as_posix()}'" ,
            ]
        )
        + "\n"
    )
    (harness / "inbox.yaml").write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale|paused",
                "",
            ]
        )
        + "\n"
    )
    (harness / "handoffs" / "2026-03-11-approval-task.yaml").write_text(
        "\n".join(
            [
                "task: approval-task",
                "to: codex-cli",
                "date: 2026-03-11",
                "status: pending_user_approval",
                "approval_gate:",
                "  required: true",
                "  approved_by_user: false",
                "  approved_at: null",
                "markdown_report: .superharness/handoffs/2026-03-11-approval-task.md",
            ]
        )
        + "\n"
    )
    return project


def test_discuss_status_lists_pending_approvals(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    result = _run_discuss_py(repo_root, args=["status", "--project", str(project)])

    assert result.returncode == 0, result.stderr
    assert "Pending user approvals:" in result.stdout
    assert "task=approval-task" in result.stdout
    assert "superharness discuss approve --task approval-task" in result.stdout


def test_discuss_approve_updates_handoff_contract_and_inbox(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)

    result = _run_discuss_py(
        repo_root,
        args=[
            "approve",
            "--project", str(project),
            "--task", "approval-task",
            "--by", "owner",
            "--note", "Approved",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "Approved consensus for task 'approval-task'" in result.stdout

    handoff_text = (project / ".superharness" / "handoffs" / "2026-03-11-approval-task.yaml").read_text()
    assert "status: approved" in handoff_text
    assert "approved_by_user: true" in handoff_text

    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "status: todo" in contract_text

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "status: pending" in inbox_text
    assert "resumed_at:" in inbox_text


def test_contract_today_shows_user_approval_required(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    script = repo_root / "src" / "superharness" / "scripts" / "contract-today.sh"

    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    assert result.returncode == 0, result.stderr
    assert "USER APPROVAL REQUIRED" in result.stdout
    assert "approve: superharness discuss approve" in result.stdout


def test_discuss_approve_auto_enqueues_when_no_paused_items(repo_root, tmp_path) -> None:
    project = _setup_project_without_paused_item(tmp_path)

    result = _run_discuss_py(
        repo_root,
        args=[
            "approve",
            "--project", str(project),
            "--task", "approval-task",
            "--by", "owner",
            "--note", "Approved",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "Auto-enqueued inbox item:" in result.stdout
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "task: approval-task" in inbox_text
    assert "to: codex-cli" in inbox_text
    assert "status: pending" in inbox_text


def test_discuss_start_requires_topic(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)

    result = _run_discuss_py(repo_root, args=["start", "--project", str(project)])

    assert result.returncode == 2
    # argparse: "the following arguments are required: --topic"
    assert "--topic" in result.stderr and ("required" in result.stderr or "is required" in result.stderr)


def test_discuss_start_enqueues_round_one_for_both_agents(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)

    result = _run_discuss_py(
        repo_root,
        args=[
            "start",
            "--project", str(project),
            "--topic", "Review monitor retry behavior",
            "--max-rounds", "2",
        ],
    )

    assert result.returncode == 0, result.stderr
    assert "Discussion started:" in result.stdout
    assert "Enqueued round 1 for claude-code:" in result.stdout
    assert "Enqueued round 1 for codex-cli:" in result.stdout

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "task: discuss-" in inbox_text
    assert "/round-1" in inbox_text
    assert "to: claude-code" in inbox_text
    assert "to: codex-cli" in inbox_text
    assert "status: pending" in inbox_text


def test_discuss_importable_without_fcntl():
    """Regression: discuss.py must be importable even when fcntl is unavailable (Windows)."""
    import unittest.mock
    blocked = {"fcntl": None}
    # Remove cached module so the fresh import is attempted with blocked fcntl
    modules_to_remove = [k for k in sys.modules if "superharness.engine.discuss" in k]
    for m in modules_to_remove:
        del sys.modules[m]
    with unittest.mock.patch.dict(sys.modules, blocked):
        import importlib
        mod = importlib.import_module("superharness.engine.discuss")
        assert hasattr(mod, "cmd_status")
        assert hasattr(mod, "cmd_approve")
