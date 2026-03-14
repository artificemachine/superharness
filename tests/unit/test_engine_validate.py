from __future__ import annotations

from pathlib import Path

from tests.helpers import run_cmd


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


def test_validate_requires_project(repo_root) -> None:
    r = _run_validate(repo_root, [])
    assert r.returncode != 0
    assert "required" in r.stderr.lower()


def test_validate_fails_missing_handoff_for_done_task(repo_root, tmp_path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: finished-task\n    status: done\n    owner: claude-code\n",
    )
    r = _run_validate(repo_root, ["--project", str(project)])
    assert r.returncode == 1
    assert "Missing handoff file for done task: finished-task" in r.stdout


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
        tasks="  - id: complete-task\n    status: done\n    owner: claude-code\n",
    )
    (project / ".superharness" / "handoffs" / "h.yaml").write_text("task: complete-task\nto: claude-code\n")
    (project / ".superharness" / "ledger.md").write_text("# Ledger\ncomplete-task done\n")
    r = _run_validate(repo_root, ["--project", str(project)])
    assert r.returncode == 0
    assert "passed" in r.stdout.lower()


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
