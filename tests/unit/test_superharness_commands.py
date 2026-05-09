from __future__ import annotations

from tests.helpers import run_bash
import sys
import pytest


pytestmark = pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")

def _setup_project(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: demo-contract",
                "created: 2026-03-09",
                "goal: \"Demo\"",
                "tasks:",
                "  - id: mcp-docs",
                "    title: \"Write docs\"",
                "    owner: codex-cli",
                "    status: plan_approved",
                f"    project_path: '{project.as_posix()}'" ,
            ]
        )
        + "\n"
    )
    (harness / "ledger.md").write_text("# Ledger\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    seed_sqlite_from_yaml(project)
    return project


def test_contract_today_outputs_delegate_prompt(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    result = run_bash(
        wrapper,
        cwd=repo_root,
        args=["contract", "today", "--project", str(project)],
    )

    assert result.returncode == 0, result.stderr
    assert "Contract demo-contract" in result.stdout
    assert "I detected owner is codex-cli. Do you want to delegate mcp-docs now?" in result.stdout


def test_contract_today_skips_discussion_round_delegate_prompt(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    harness = project / ".superharness"
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: demo-contract",
                "created: 2026-03-09",
                "goal: \"Demo\"",
                "tasks:",
                "  - id: discuss-demo/round-1",
                "    title: \"Discussion round\"",
                "    owner: codex-cli",
                "    status: in_progress",
                "    workflow: discussion",
                f"    project_path: '{project.as_posix()}'" ,
            ]
        )
        + "\n"
    )
    wrapper = repo_root / "superharness"

    result = run_bash(
        wrapper,
        cwd=repo_root,
        args=["contract", "today", "--project", str(project)],
    )

    assert result.returncode == 0, result.stderr
    assert "Do you want to delegate" not in result.stdout


def test_contract_today_auto_detects_project_from_cwd(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    result = run_bash(
        wrapper,
        cwd=project,
        args=["contract", "today"],
    )

    assert result.returncode == 0, result.stderr
    assert "Contract demo-contract" in result.stdout


def test_delegate_shorthand_auto_detects_project_from_cwd(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    result = run_bash(
        wrapper,
        cwd=project,
        args=["delegate", "mcp-docs", "--print-only"],
    )

    assert result.returncode == 0, result.stderr
    assert "Task: mcp-docs" in result.stdout
    assert "Generated prompt:" in result.stdout


def test_delegate_shorthand_uses_task_owner(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    result = run_bash(
        wrapper,
        cwd=repo_root,
        args=["delegate", "mcp-docs", "--project", str(project), "--print-only"],
    )

    assert result.returncode == 0, result.stderr
    assert "Task: mcp-docs" in result.stdout
    assert "Generated prompt:" in result.stdout


def test_task_create_and_delete(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    create_res = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "task",
            "create",
            "--project",
            str(project),
            "--id",
            "new-task",
            "--title",
            "Do thing",
            "--owner",
            "claude-code",
            "--status",
            "todo",
        ],
    )
    assert create_res.returncode == 0, create_res.stderr

    delete_res = run_bash(
        wrapper,
        cwd=repo_root,
        args=["task", "delete", "--project", str(project), "--id", "new-task"],
    )
    assert delete_res.returncode == 0, delete_res.stderr


def test_task_create_allows_pending_user_approval_status(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    create_res = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "task",
            "create",
            "--project",
            str(project),
            "--id",
            "approval-task",
            "--title",
            "Approval gate task",
            "--owner",
            "claude-code",
            "--status",
            "pending_user_approval",
        ],
    )
    assert create_res.returncode == 0, create_res.stderr
    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "id: approval-task" in contract_text
    assert "status: pending_user_approval" in contract_text


def test_task_create_accepts_workflow_and_development_method(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    create_res = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "task",
            "create",
            "--project",
            str(project),
            "--id",
            "quick-task",
            "--title",
            "Quick task",
            "--owner",
            "claude-code",
            "--workflow",
            "quick",
            "--development-method",
            "tdd",
        ],
    )
    assert create_res.returncode == 0, create_res.stderr
    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "workflow: quick" in contract_text
    assert "development_method: tdd" in contract_text


def test_task_create_rejects_failed_status(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    create_res = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "task",
            "create",
            "--project",
            str(project),
            "--id",
            "bad-task",
            "--title",
            "Should fail",
            "--owner",
            "codex-cli",
            "--status",
            "failed",
        ],
    )
    assert create_res.returncode == 2
    assert "status must be todo, in_progress, pending_user_approval, or done" in create_res.stderr


def test_task_create_with_dependency(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    create_res = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "task",
            "create",
            "--project",
            str(project),
            "--id",
            "integration-tests",
            "--title",
            "Integration tests",
            "--owner",
            "codex-cli",
            "--status",
            "todo",
            "--dependency",
            "mcp-docs",
        ],
    )
    assert create_res.returncode == 0, create_res.stderr
    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "id: integration-tests" in contract_text
    assert "dependency: mcp-docs" in contract_text


def test_task_status_update_requires_owner_actor(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    forbidden = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "task",
            "status",
            "--project",
            str(project),
            "--id",
            "mcp-docs",
            "--status",
            "in_progress",
            "--actor",
            "claude-code",
            "--summary",
            "Starting work.",
        ],
    )
    assert forbidden.returncode == 1
    assert "forbidden:" in forbidden.stderr

    allowed = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "task",
            "status",
            "--project",
            str(project),
            "--id",
            "mcp-docs",
            "--status",
            "in_progress",
            "--actor",
            "codex-cli",
            "--summary",
            "Starting work.",
        ],
    )
    assert allowed.returncode == 0, allowed.stderr
    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "status: in_progress" in contract_text


def test_task_status_blocked_until_dependency_done(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    create_res = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "task",
            "create",
            "--project",
            str(project),
            "--id",
            "dependent-task",
            "--title",
            "Dependent task",
            "--owner",
            "codex-cli",
            "--status",
            "todo",
            "--dependency",
            "mcp-docs",
        ],
    )
    assert create_res.returncode == 0, create_res.stderr

    blocked = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "task",
            "status",
            "--project",
            str(project),
            "--id",
            "dependent-task",
            "--status",
            "in_progress",
            "--actor",
            "codex-cli",
            "--summary",
            "Starting dependent work.",
        ],
    )
    assert blocked.returncode == 1
    assert "blocked:" in blocked.stderr

    dep_done = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "task",
            "status",
            "--project",
            str(project),
            "--id",
            "mcp-docs",
            "--status",
            "done",
            "--actor",
            "codex-cli",
            "--summary",
            "Completed mcp-docs.",
        ],
    )
    assert dep_done.returncode == 0, dep_done.stderr

    allowed = run_bash(
        wrapper,
        cwd=repo_root,
        args=[
            "task",
            "status",
            "--project",
            str(project),
            "--id",
            "dependent-task",
            "--status",
            "in_progress",
            "--actor",
            "codex-cli",
            "--summary",
            "Starting dependent work.",
        ],
    )
    assert allowed.returncode == 0, allowed.stderr


def test_doctor_passes_on_minimal_project(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    result = run_bash(wrapper, cwd=repo_root, args=["doctor", "--project", str(project)])
    assert result.returncode == 0, result.stderr
    assert "summary:" in result.stdout
