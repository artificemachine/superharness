from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.helpers import REPO_ROOT


def _run_python(args: list[str]) -> subprocess.CompletedProcess:
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.inbox_enqueue"] + args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


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

    result = _run_python(["--project", str(project), "--to", "codex-cli", "--task", "mcp-docs"])

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "missing project_path" in combined or "project_path" in combined


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

    result = _run_python(["--project", str(project), "--to", "codex-cli", "--task", "mcp-docs"])

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "project_path mismatch" in combined or "mismatch" in combined


def test_enqueue_rejects_invalid_task_token(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-invalid-task")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks: []",
        ],
    )

    result = _run_python(["--project", str(project), "--to", "codex-cli", "--task", "bad|task"])

    assert result.returncode in (1, 2)
    combined = result.stdout + result.stderr
    assert "task id" in combined.lower() or "invalid" in combined.lower() or "match" in combined.lower()


def test_enqueue_rejects_invalid_custom_item_id(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-invalid-id")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks: []",
        ],
    )

    result = _run_python(
        [
            "--project",
            str(project),
            "--to",
            "codex-cli",
            "--task",
            "mcp-docs",
            "--id",
            "bad\nid",
        ]
    )

    assert result.returncode in (1, 2)
    combined = result.stdout + result.stderr
    assert "inbox id" in combined.lower() or "invalid" in combined.lower() or "match" in combined.lower()
