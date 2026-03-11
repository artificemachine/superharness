from __future__ import annotations

from pathlib import Path

from tests.helpers import run_bash


def _setup_project(tmp_path: Path, name: str) -> Path:
    project = tmp_path / name
    project.mkdir()
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    return project


def _write_contract(project: Path, lines: list[str]) -> None:
    (project / ".superharness" / "contract.yaml").write_text("\n".join(lines) + "\n")


def test_enqueue_fails_when_task_project_path_missing(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-missing-path")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: mcp-docs",
            "    title: docs",
        ],
    )

    script = repo_root / "scripts" / "inbox-enqueue.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli", "--task", "mcp-docs"],
    )

    assert result.returncode == 1
    assert "missing project_path" in result.stderr


def test_enqueue_fails_when_task_project_path_mismatch(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-mismatch")
    other = tmp_path / "other-project"
    other.mkdir()
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: mcp-docs",
            f'    project_path: "{other}"',
        ],
    )

    script = repo_root / "scripts" / "inbox-enqueue.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli", "--task", "mcp-docs"],
    )

    assert result.returncode == 1
    assert "project_path mismatch" in result.stderr


def test_enqueue_rejects_invalid_task_token(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-invalid-task")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks: []",
        ],
    )

    script = repo_root / "scripts" / "inbox-enqueue.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--to", "codex-cli", "--task", "bad|task"],
    )

    assert result.returncode == 2
    assert "task id must match" in result.stderr


def test_enqueue_rejects_invalid_custom_item_id(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-invalid-id")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks: []",
        ],
    )

    script = repo_root / "scripts" / "inbox-enqueue.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project",
            str(project),
            "--to",
            "codex-cli",
            "--task",
            "mcp-docs",
            "--id",
            "bad\nid",
        ],
    )

    assert result.returncode == 2
    assert "Invalid inbox id" in result.stderr
