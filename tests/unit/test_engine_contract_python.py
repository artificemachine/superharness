"""Python-native tests for superharness.engine.contract (no Ruby subprocess)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PYTHON = sys.executable


def _run_contract(cmd: str, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.engine.contract", cmd] + args,
        capture_output=True,
        text=True,
        check=False,
    )


def _contract_file(tmp_path: Path) -> Path:
    f = tmp_path / "contract.yaml"
    f.write_text(
        "id: test-contract-123\n"
        "tasks:\n"
        "  - id: task-a\n"
        "    owner: claude-code\n"
        "    status: todo\n"
        '    project_path: "/some/path"\n'
        "    deadline_minutes: 45\n"
        "  - id: task-b\n"
        "    owner: codex-cli\n"
        "    status: done\n"
        '    project_path: "/other/path"\n'
    )
    return f


def test_task_exists_true(tmp_path: Path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract("task_exists", ["--file", str(f), "--task", "task-a"])
    assert r.returncode == 0
    assert r.stdout.strip() == "true"


def test_task_exists_false(tmp_path: Path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract("task_exists", ["--file", str(f), "--task", "nonexistent"])
    assert r.returncode == 0
    assert r.stdout.strip() == "false"


def test_task_exists_empty_contract(tmp_path: Path) -> None:
    f = tmp_path / "empty.yaml"
    f.write_text("id: empty\n")
    r = _run_contract("task_exists", ["--file", str(f), "--task", "anything"])
    assert r.returncode == 0
    assert r.stdout.strip() == "false"


def test_task_owner(tmp_path: Path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract("task_owner", ["--file", str(f), "--task", "task-a"])
    assert r.returncode == 0
    assert r.stdout.strip() == "claude-code"


def test_task_owner_missing_task(tmp_path: Path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract("task_owner", ["--file", str(f), "--task", "nope"])
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_task_status(tmp_path: Path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract("task_status", ["--file", str(f), "--task", "task-b"])
    assert r.returncode == 0
    assert r.stdout.strip() == "done"


def test_task_project_path(tmp_path: Path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract("task_project_path", ["--file", str(f), "--task", "task-a"])
    assert r.returncode == 0
    assert r.stdout.strip() == "/some/path"


def test_contract_id(tmp_path: Path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract("contract_id", ["--file", str(f)])
    assert r.returncode == 0
    assert r.stdout.strip() == "test-contract-123"


def test_task_deadline_minutes(tmp_path: Path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract("task_deadline_minutes", ["--file", str(f), "--task", "task-a"])
    assert r.returncode == 0
    assert r.stdout.strip() == "45"


def test_task_deadline_minutes_missing(tmp_path: Path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract("task_deadline_minutes", ["--file", str(f), "--task", "task-b"])
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_latest_handoff_task(tmp_path: Path) -> None:
    handoff_dir = tmp_path / "handoffs"
    handoff_dir.mkdir()
    (handoff_dir / "h1.yaml").write_text("task: task-a\nto: claude-code\n")
    (handoff_dir / "h2.yaml").write_text("task: task-b\nto: codex-cli\n")
    r = _run_contract("latest_handoff_task", ["--dir", str(handoff_dir), "--to", "codex-cli"])
    assert r.returncode == 0
    assert "task-b" in r.stdout


def test_latest_handoff_task_no_match(tmp_path: Path) -> None:
    handoff_dir = tmp_path / "handoffs"
    handoff_dir.mkdir()
    (handoff_dir / "h1.yaml").write_text("task: task-a\nto: claude-code\n")
    r = _run_contract("latest_handoff_task", ["--dir", str(handoff_dir), "--to", "codex-cli"])
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_nonexistent_file(tmp_path: Path) -> None:
    r = _run_contract("task_exists", ["--file", str(tmp_path / "nope.yaml"), "--task", "x"])
    assert r.returncode == 0
    assert r.stdout.strip() == "false"
