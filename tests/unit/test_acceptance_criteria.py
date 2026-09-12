from __future__ import annotations

import os
import subprocess
import sys
import yaml
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT, run_bash, run_cmd

_skip_win = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _run_delegate_py(cwd, args: list[str] | None = None, env: dict | None = None):
    """Run delegate Python module."""
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(REPO_ROOT / "src")
    if env:
        for k, v in env.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
    cmd = [sys.executable, "-m", "superharness.commands.delegate"] + (args or [])
    return subprocess.run(
        cmd, cwd=str(cwd), text=True, capture_output=True, env=merged, check=False
    )


def _setup_project(tmp_path: Path, status: str = "plan_approved") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: test-contract",
                "created: '2026-01-01T00:00:00Z'",
                "created_by: owner",
                "status: active",
                "tasks:",
                "  - id: existing-task",
                "    title: Existing task",
                "    owner: codex-cli",
                f"    status: {status}",
                f"    project_path: '{project.as_posix()}'",
            ]
        )
        + "\n"
    )
    from tests.helpers import seed_sqlite_from_yaml

    seed_sqlite_from_yaml(project)
    return project


# ── task.sh create --criteria ──






# ── engine/contract.py task_acceptance_criteria ──


def test_engine_reads_acceptance_criteria(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    contract_file = project / ".superharness" / "contract.yaml"
    doc = yaml.safe_load(contract_file.read_text())
    doc["tasks"][0]["acceptance_criteria"] = ["Criterion A", "Criterion B"]
    contract_file.write_text(yaml.dump(doc))

    import sys

    result = run_cmd(
        [
            sys.executable,
            "-m",
            "superharness.engine.contract",
            "task_acceptance_criteria",
            "--file",
            str(contract_file),
            "--task",
            "existing-task",
        ],
        cwd=repo_root,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert lines == ["Criterion A", "Criterion B"]


def test_engine_returns_empty_when_no_criteria(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    contract_file = project / ".superharness" / "contract.yaml"

    import sys

    result = run_cmd(
        [
            sys.executable,
            "-m",
            "superharness.engine.contract",
            "task_acceptance_criteria",
            "--file",
            str(contract_file),
            "--task",
            "existing-task",
        ],
        cwd=repo_root,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ── delegate.sh injects criteria into prompt ──




def test_delegate_prompt_omits_criteria_when_none(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "existing-task",
            "--print-only",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "Acceptance criteria" not in result.stdout


# ── task.sh status=done warns about criteria ──




@_skip_win
def test_task_status_done_no_warning_without_criteria(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, status="review_passed")
    script = repo_root / "src" / "superharness" / "scripts" / "task.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "status",
            "--project",
            str(project),
            "--id",
            "existing-task",
            "--status",
            "done",
            "--actor",
            "codex-cli",
            "--summary",
            "Completed",
        ],
    )
    assert result.returncode == 0, result.stderr
    assert "acceptance criteria" not in result.stderr
