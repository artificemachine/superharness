from __future__ import annotations

from pathlib import Path

from tests.helpers import run_bash, seed_sqlite_from_yaml
import sys
import pytest


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


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
                "    verified: true",
                f"    project_path: '{project.as_posix()}'",
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
    seed_sqlite_from_yaml(project)
    from tests.helpers import seed_sqlite_handoff, seed_sqlite_ledger

    seed_sqlite_handoff(
        project,
        "done-task",
        phase="report",
        status="done",
        content="task: done-task\n",
        now="2026-03-08T00:00:00Z",
    )
    seed_sqlite_ledger(
        project,
        action="done-task completed",
        task_id="done-task",
        now="2026-03-08T00:00:00Z",
    )


def test_contract_hygiene_passes_for_done_task_with_evidence(
    repo_root, tmp_path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_project(project)

    script = (
        repo_root / "src" / "superharness" / "scripts" / "check-contract-hygiene.sh"
    )
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Contract hygiene check passed" in result.stdout






def test_contract_hygiene_strict_passes_when_failures_are_promoted(
    repo_root, tmp_path
) -> None:
    project = tmp_path / "proj4"
    project.mkdir()
    _write_project(project)

    (project / ".superharness" / "contract.yaml").write_text(
        "\n".join(
            [
                "id: test-contract",
                "tasks:",
                "  - id: done-task",
                "    status: done",
                "    verified: true",
                f"    project_path: '{project.as_posix()}'",
                "decisions: []",
                "failures:",
                "  - date: 2026-03-10",
                "    by: codex-cli",
                "    summary: launch status drift not recovered",
            ]
        )
        + "\n"
    )
    (project / ".superharness" / "failures.yaml").write_text(
        "\n".join(
            [
                "failures:",
                "  - date: 2026-03-10",
                "    source_task: done-task",
                "    by: codex-cli",
                "    summary: launch status drift not recovered",
                "    mitigation: run inbox recovery before dispatch",
                "    promoted: false",
            ]
        )
        + "\n"
    )

    script = (
        repo_root / "src" / "superharness" / "scripts" / "check-contract-hygiene.sh"
    )
    result = run_bash(
        script, cwd=repo_root, args=["--project", str(project), "--strict"]
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Contract hygiene check passed" in result.stdout
