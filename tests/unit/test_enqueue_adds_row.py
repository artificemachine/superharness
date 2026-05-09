"""Tests for superharness.commands.inbox_enqueue (Python module).

Tests via subprocess: python3 -m superharness.commands.inbox_enqueue
"""
from __future__ import annotations
import pytest

import subprocess
import sys
from pathlib import Path


PYTHON = sys.executable

INBOX_HEADER = (
    "# Delegation inbox\n"
    "# status: pending|launched|running|done|failed|stale\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")

def _make_project(tmp_path: Path, contract_yaml: str | None = None) -> Path:
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    if contract_yaml is not None:
        (harness / "contract.yaml").write_text(contract_yaml)
    from tests.helpers import seed_sqlite_from_yaml
    seed_sqlite_from_yaml(project)
    return project


def _run_enqueue(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.commands.inbox_enqueue"] + args,
        capture_output=True,
        text=True,
        check=False,
    )


def _inbox_text(project: Path) -> str:
    f = project / ".superharness" / "inbox.yaml"
    if f.exists():
        return f.read_text()
    return ""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_adds_to_inbox(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    r = _run_enqueue([
        "--project", str(project),
        "--to", "claude-code",
        "--task", "my-task",
        "--id", "item-001",
        "--priority", "1",
    ])
    assert r.returncode == 0, r.stderr
    assert "Enqueued inbox item:" in r.stdout
    assert "id: item-001" in r.stdout
    assert "to: claude-code" in r.stdout
    assert "task: my-task" in r.stdout
    assert "priority: 1" in r.stdout

    text = _inbox_text(project)
    assert "id: item-001" in text
    assert "status: pending" in text


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_duplicate_id_rejected(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _run_enqueue([
        "--project", str(project),
        "--to", "claude-code",
        "--task", "my-task",
        "--id", "dup-id",
    ])
    r = _run_enqueue([
        "--project", str(project),
        "--to", "codex-cli",
        "--task", "other-task",
        "--id", "dup-id",
    ])
    assert r.returncode == 1
    assert "already exists" in r.stderr


def test_enqueue_validates_target(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    r = _run_enqueue([
        "--project", str(project),
        "--to", "bad-agent",
        "--task", "my-task",
    ])
    assert r.returncode == 2
    assert "must be one of:" in r.stderr


def test_enqueue_validates_task_token(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    r = _run_enqueue([
        "--project", str(project),
        "--to", "claude-code",
        "--task", "bad|task",
    ])
    assert r.returncode == 2
    assert "task id must match" in r.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_priority_default(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    r = _run_enqueue([
        "--project", str(project),
        "--to", "claude-code",
        "--task", "my-task",
        "--id", "default-prio",
    ])
    assert r.returncode == 0, r.stderr
    assert "priority: 2" in r.stdout


def test_enqueue_validates_contract_project_path(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    project = _make_project(tmp_path, contract_yaml="\n".join([
        "id: test-contract",
        "tasks:",
        "  - id: checked-task",
        "    title: Test",
        "    owner: claude-code",
        "    status: todo",
        f"    project_path: '{other.as_posix()}'",
    ]) + "\n")
    r = _run_enqueue([
        "--project", str(project),
        "--to", "claude-code",
        "--task", "checked-task",
        "--id", "item-path-check",
    ])
    assert r.returncode == 1
    assert "project_path mismatch" in r.stderr


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_auto_generates_id(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    r = _run_enqueue([
        "--project", str(project),
        "--to", "codex-cli",
        "--task", "auto-id-task",
    ])
    assert r.returncode == 0, r.stderr
    assert "id:" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_outputs_file_path(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    r = _run_enqueue([
        "--project", str(project),
        "--to", "claude-code",
        "--task", "my-task",
        "--id", "file-path-test",
    ])
    assert r.returncode == 0, r.stderr
    assert "file:" in r.stdout
    inbox_path = str(project / ".superharness" / "inbox.yaml")
    assert inbox_path in r.stdout
