"""Python-native tests for superharness.engine.validate (no Ruby subprocess)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

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


def test_validate_requires_project() -> None:
    r = _run_validate([])
    assert r.returncode != 0
    assert "required" in r.stderr.lower()


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
        tasks="  - id: complete-task\n    status: done\n    owner: claude-code\n",
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
