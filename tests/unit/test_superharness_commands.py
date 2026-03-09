from __future__ import annotations

from tests.helpers import run_bash


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
                "    status: todo",
                f'    project_path: "{project}"',
            ]
        )
        + "\n"
    )
    (harness / "ledger.md").write_text("# Ledger\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
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


def test_doctor_passes_on_minimal_project(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    wrapper = repo_root / "superharness"

    result = run_bash(wrapper, cwd=repo_root, args=["doctor", "--project", str(project)])
    assert result.returncode == 0, result.stderr
    assert "summary:" in result.stdout
