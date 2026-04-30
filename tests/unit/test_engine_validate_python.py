"""Python-native tests for superharness.engine.validate (no Ruby subprocess)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml, get_task_from_sqlite


PYTHON = sys.executable


def _write_project(
    tmp_path: Path,
    *,
    tasks: str = "",
    decisions: str = "[]",
    failures: str = "[]",
) -> Path:
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


def _run_validate(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.engine.validate"] + args,
        capture_output=True,
        text=True,
        check=False,
    )


def test_validate_help() -> None:
    r = _run_validate(["--help"])
    assert r.returncode == 0
    assert "Usage:" in r.stdout
    assert "--project" in r.stdout
    assert "--strict" in r.stdout


def test_validate_passes_clean_project(tmp_path: Path) -> None:
    project = _write_project(tmp_path)
    r = _run_validate(["--project", str(project)])
    assert r.returncode == 0
    assert "passed" in r.stdout.lower()


def test_validate_defaults_to_cwd() -> None:
    # --project is optional; when omitted, validate uses cwd.
    # Must not raise an argparse "required argument missing" error.
    # (validate's own "Missing required path" messages are expected and allowed.)
    r = _run_validate([])
    assert "the following arguments are required" not in r.stderr.lower()


def test_validate_fails_missing_handoff_for_done_task(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: finished-task\n    status: done\n    owner: claude-code\n",
    )
    r = _run_validate(["--project", str(project)])
    assert r.returncode == 1
    assert "Missing handoff file for done task: finished-task" in r.stdout


def test_validate_fails_missing_ledger_for_done_task(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: ledger-task\n    status: done\n    owner: claude-code\n",
    )
    (project / ".superharness" / "handoffs" / "h.yaml").write_text("task: ledger-task\nto: claude-code\n")
    r = _run_validate(["--project", str(project)])
    assert r.returncode == 1
    assert "Missing ledger mention for done task: ledger-task" in r.stdout


def test_validate_passes_done_task_with_handoff_and_ledger(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: complete-task\n    status: done\n    owner: claude-code\n    verified: true\n",
    )
    (project / ".superharness" / "handoffs" / "h.yaml").write_text("task: complete-task\nto: claude-code\n")
    (project / ".superharness" / "ledger.md").write_text("# Ledger\ncomplete-task done\n")
    r = _run_validate(["--project", str(project)])
    assert r.returncode == 0
    assert "passed" in r.stdout.lower()


def test_validate_strict_warns_empty_stores(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        decisions="[{id: d1, title: test}]",
    )
    r = _run_validate(["--project", str(project), "--strict"])
    assert r.returncode == 1
    assert "decisions.yaml is empty" in r.stdout


def test_validate_missing_protocol_dir(tmp_path: Path) -> None:
    project = tmp_path / "empty"
    project.mkdir()
    r = _run_validate(["--project", str(project)])
    assert r.returncode == 1
    assert "Missing required path" in r.stderr


def test_validate_invalid_effort_value(tmp_path: Path) -> None:
    project = _write_project(
        tmp_path,
        tasks="  - id: bad-effort-task\n    status: in_progress\n    owner: claude-code\n    effort: extreme\n",
    )
    r = _run_validate(["--project", str(project)])
    assert r.returncode == 1
    assert "invalid effort='extreme'" in r.stdout


def test_validate_valid_effort_values_pass(tmp_path: Path) -> None:
    for effort in ("low", "medium", "high", "max"):
        subdir = tmp_path / effort
        subdir.mkdir()
        project = _write_project(
            subdir,
            tasks=f"  - id: task-{effort}\n    status: todo\n    owner: claude-code\n    effort: {effort}\n",
        )
        r = _run_validate(["--project", str(project)])
        assert r.returncode == 0, f"effort={effort!r} should be valid, got: {r.stdout}"


def test_validate_null_effort_passes(tmp_path: Path) -> None:
    # Tasks with no effort field should pass — effort is optional
    project = _write_project(
        tmp_path,
        tasks="  - id: no-effort-task\n    status: todo\n    owner: claude-code\n",
    )
    r = _run_validate(["--project", str(project)])
    assert r.returncode == 0
