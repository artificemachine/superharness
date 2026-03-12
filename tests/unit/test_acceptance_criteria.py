from __future__ import annotations

import yaml
from pathlib import Path

from tests.helpers import run_bash, run_cmd


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: test-contract",
                "tasks:",
                "  - id: existing-task",
                "    owner: codex-cli",
                "    status: todo",
                f'    project_path: "{project}"',
            ]
        )
        + "\n"
    )
    return project


# ── task.sh create --criteria ──


def test_task_create_with_criteria(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    script = repo_root / "scripts" / "task.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "create",
            "--project", str(project),
            "--id", "my-task",
            "--title", "Test task",
            "--owner", "claude-code",
            "--criteria", "All tests pass",
            "--criteria", "No lint errors",
        ],
    )
    assert result.returncode == 0, result.stderr
    assert "Created task" in result.stdout

    contract = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
    task = next(t for t in contract["tasks"] if t["id"] == "my-task")
    assert task["acceptance_criteria"] == ["All tests pass", "No lint errors"]


def test_task_create_without_criteria_omits_field(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    script = repo_root / "scripts" / "task.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "create",
            "--project", str(project),
            "--id", "no-ac-task",
            "--title", "No criteria",
            "--owner", "codex-cli",
        ],
    )
    assert result.returncode == 0, result.stderr

    contract = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
    task = next(t for t in contract["tasks"] if t["id"] == "no-ac-task")
    assert "acceptance_criteria" not in task


# ── engine/contract.rb task_acceptance_criteria ──


def test_engine_reads_acceptance_criteria(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    contract_file = project / ".superharness" / "contract.yaml"
    doc = yaml.safe_load(contract_file.read_text())
    doc["tasks"][0]["acceptance_criteria"] = ["Criterion A", "Criterion B"]
    contract_file.write_text(yaml.dump(doc))

    engine = repo_root / "engine" / "contract.rb"
    result = run_cmd(
        ["ruby", str(engine), "task_acceptance_criteria", "--file", str(contract_file), "--task", "existing-task"],
        cwd=repo_root,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert lines == ["Criterion A", "Criterion B"]


def test_engine_returns_empty_when_no_criteria(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    contract_file = project / ".superharness" / "contract.yaml"

    engine = repo_root / "engine" / "contract.rb"
    result = run_cmd(
        ["ruby", str(engine), "task_acceptance_criteria", "--file", str(contract_file), "--task", "existing-task"],
        cwd=repo_root,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


# ── delegate.sh injects criteria into prompt ──


def test_delegate_prompt_includes_criteria(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    contract_file = project / ".superharness" / "contract.yaml"
    doc = yaml.safe_load(contract_file.read_text())
    doc["tasks"][0]["acceptance_criteria"] = ["Tests green", "Coverage > 60%"]
    contract_file.write_text(yaml.dump(doc))

    script = repo_root / "scripts" / "delegate.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "existing-task", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "Acceptance criteria" in result.stdout
    assert "- Tests green" in result.stdout
    assert "- Coverage > 60%" in result.stdout


def test_delegate_prompt_omits_criteria_when_none(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    script = repo_root / "scripts" / "delegate.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "existing-task", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert "Acceptance criteria" not in result.stdout


# ── task.sh status=done warns about criteria ──


def test_task_status_done_warns_about_criteria(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    contract_file = project / ".superharness" / "contract.yaml"
    doc = yaml.safe_load(contract_file.read_text())
    doc["tasks"][0]["acceptance_criteria"] = ["All tests pass"]
    contract_file.write_text(yaml.dump(doc))

    script = repo_root / "scripts" / "task.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "status",
            "--project", str(project),
            "--id", "existing-task",
            "--status", "done",
            "--actor", "codex-cli",
            "--summary", "Completed",
        ],
    )
    assert result.returncode == 0, result.stderr
    assert "acceptance criteria" in result.stderr
    assert "All tests pass" in result.stderr


def test_task_status_done_no_warning_without_criteria(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    script = repo_root / "scripts" / "task.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "status",
            "--project", str(project),
            "--id", "existing-task",
            "--status", "done",
            "--actor", "codex-cli",
            "--summary", "Completed",
        ],
    )
    assert result.returncode == 0, result.stderr
    assert "acceptance criteria" not in result.stderr
