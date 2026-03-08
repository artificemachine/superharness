from __future__ import annotations

from pathlib import Path

from tests.helpers import run_bash


def _write_project(project: Path) -> None:
    harness = project / ".superharness"
    handoffs = harness / "handoffs"
    handoffs.mkdir(parents=True, exist_ok=True)

    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: test-contract",
                "tasks:",
                "  - id: done-task",
                "    status: done",
                f'    project_path: "{project}"',
                "decisions:",
                "  - date: 2026-03-08",
                "    by: codex-cli",
                "    decision: keep check",
                "failures: []",
            ]
        )
        + "\n"
    )
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    (harness / "ledger.md").write_text("# Ledger\n- 2026-03-08 done-task completed\n")
    (handoffs / "2026-03-08-done-task.yaml").write_text("task: done-task\n")


def test_contract_hygiene_passes_for_done_task_with_evidence(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_project(project)

    script = repo_root / "scripts" / "check-contract-hygiene.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Contract hygiene check passed" in result.stdout


def test_contract_hygiene_strict_fails_when_decisions_not_promoted(repo_root, tmp_path) -> None:
    project = tmp_path / "proj2"
    project.mkdir()
    _write_project(project)

    script = repo_root / "scripts" / "check-contract-hygiene.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project), "--strict"])

    assert result.returncode == 1
    assert "Contract has decisions but decisions.yaml is empty" in result.stdout
