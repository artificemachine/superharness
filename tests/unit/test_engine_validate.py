from __future__ import annotations
import pytest

from pathlib import Path

from tests.helpers import run_cmd, seed_sqlite_from_yaml


def _write_project(tmp_path: Path, *, tasks: str = "", decisions: str = "[]", failures: str = "[]") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()
    (harness / "contract.yaml").write_text(
        f"id: test\ntasks:\n{tasks}"
        f"decisions: {decisions}\n"
        f"failures: {failures}\n"
    )
    (harness / "ledger.md").write_text("# Ledger\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    seed_sqlite_from_yaml(project)
    return project


def _run_validate(repo_root: Path, args: list[str]) -> object:
    import sys
    return run_cmd(
        [sys.executable, "-m", "superharness.engine.validate"] + args,
        cwd=repo_root,
    )


def test_validate_help(repo_root) -> None:
    r = _run_validate(repo_root, ["--help"])
    assert r.returncode == 0
    assert "Usage:" in r.stdout
    assert "--project" in r.stdout
    assert "--strict" in r.stdout


def test_validate_passes_clean_project(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)
    r = _run_validate(repo_root, ["--project", str(project)])
    assert r.returncode == 0
    assert "passed" in r.stdout.lower()


def test_validate_defaults_to_cwd(repo_root) -> None:
    # --project is optional; when omitted, validate uses cwd.
    # Must not raise an argparse "required argument missing" error.
    # (validate's own "Missing required path" messages are expected and allowed.)
    r = _run_validate(repo_root, [])
    assert "the following arguments are required" not in r.stderr.lower()


def test_validate_fails_missing_handoff_for_done_task(repo_root, tmp_path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: finished-task\n    status: done\n    owner: claude-code\n",
    )
    r = _run_validate(repo_root, ["--project", str(project)])
    assert r.returncode == 1
    assert "Missing handoff for done task: finished-task" in r.stdout


def test_validate_fails_missing_ledger_for_done_task(repo_root, tmp_path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: ledger-task\n    status: done\n    owner: claude-code\n",
    )
    # Create a handoff file so only ledger check fails
    (project / ".superharness" / "handoffs" / "h.yaml").write_text("task: ledger-task\nto: claude-code\n")
    r = _run_validate(repo_root, ["--project", str(project)])
    assert r.returncode == 1
    assert "Missing ledger mention for done task: ledger-task" in r.stdout


def test_validate_passes_done_task_with_handoff_and_ledger(repo_root, tmp_path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: complete-task\n    status: done\n    owner: claude-code\n    verified: true\n",
    )
    from tests.helpers import seed_sqlite_handoff, seed_sqlite_ledger
    seed_sqlite_handoff(project, "complete-task", phase="report", status="done",
                        content="task: complete-task\nto: claude-code\n")
    seed_sqlite_ledger(project, action="complete-task done", task_id="complete-task")
    r = _run_validate(repo_root, ["--project", str(project)])
    assert r.returncode == 0
    assert "passed" in r.stdout.lower()


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_validate_strict_warns_empty_stores(repo_root, tmp_path) -> None:
    project = _write_project(
        tmp_path,
        decisions="[{id: d1, title: test}]",
    )
    r = _run_validate(repo_root, ["--project", str(project), "--strict"])
    assert r.returncode == 1
    assert "decisions.yaml is empty" in r.stdout


def test_validate_missing_protocol_dir(repo_root, tmp_path) -> None:
    project = tmp_path / "empty"
    project.mkdir()
    r = _run_validate(repo_root, ["--project", str(project)])
    assert r.returncode == 1
    assert "Missing required path" in r.stderr
