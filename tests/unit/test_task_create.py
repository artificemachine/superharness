"""Tests for superharness.commands.task (Python module).

Tests create/delete/status operations via subprocess (python3 -m superharness.commands.task).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_contract(tmp_path: Path, tasks: list[dict] | None = None) -> tuple[Path, Path]:
    """Returns (project_dir, contract_file)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    contract = harness / "contract.yaml"

    if tasks is None:
        tasks = []

    lines = ["id: test-contract", "tasks:"]
    for t in tasks:
        lines.append(f"  - id: {t['id']}")
        lines.append(f"    title: {t.get('title', 'Test')}")
        lines.append(f"    owner: {t.get('owner', 'claude-code')}")
        lines.append(f"    status: {t.get('status', 'todo')}")
        lines.append(f"    project_path: '{project.as_posix()}'" )
        if "dependency" in t:
            lines.append(f"    dependency: {t['dependency']}")

    contract.write_text("\n".join(lines) + "\n")
    return project, contract


def _run_task(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.commands.task"] + args,
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

def test_task_create_adds_to_contract(tmp_path: Path) -> None:
    project, contract = _make_contract(tmp_path)
    r = _run_task([
        "create",
        "--project", str(project),
        "--id", "new-task",
        "--title", "A new task",
        "--owner", "claude-code",
        "--status", "todo",
    ])
    assert r.returncode == 0, r.stderr
    assert "Created task 'new-task'" in r.stdout
    assert "owner=claude-code" in r.stdout
    assert "status=todo" in r.stdout
    text = contract.read_text()
    assert "id: new-task" in text


def test_task_create_duplicate_fails(tmp_path: Path) -> None:
    project, contract = _make_contract(tmp_path, [{"id": "existing"}])
    r = _run_task([
        "create",
        "--project", str(project),
        "--id", "existing",
        "--title", "Another",
        "--owner", "claude-code",
    ])
    assert r.returncode != 0
    assert "already exists" in r.stderr


def test_task_create_validates_owner(tmp_path: Path) -> None:
    project, _ = _make_contract(tmp_path)
    r = _run_task([
        "create",
        "--project", str(project),
        "--id", "bad-owner",
        "--title", "Test",
        "--owner", "invalid-agent",
    ])
    assert r.returncode != 0
    assert "owner must be claude-code or codex-cli" in r.stderr


def test_task_create_validates_status(tmp_path: Path) -> None:
    project, _ = _make_contract(tmp_path)
    r = _run_task([
        "create",
        "--project", str(project),
        "--id", "bad-status",
        "--title", "Test",
        "--owner", "claude-code",
        "--status", "flying",
    ])
    assert r.returncode != 0
    assert "status must be" in r.stderr


def test_task_create_with_dependency(tmp_path: Path) -> None:
    project, contract = _make_contract(tmp_path, [{"id": "dep-task"}])
    r = _run_task([
        "create",
        "--project", str(project),
        "--id", "child-task",
        "--title", "Child",
        "--owner", "codex-cli",
        "--dependency", "dep-task",
    ])
    assert r.returncode == 0, r.stderr
    assert "dependency=dep-task" in r.stdout
    text = contract.read_text()
    assert "dependency: dep-task" in text


def test_task_create_dependency_not_found(tmp_path: Path) -> None:
    project, _ = _make_contract(tmp_path)
    r = _run_task([
        "create",
        "--project", str(project),
        "--id", "orphan",
        "--title", "Orphan",
        "--owner", "claude-code",
        "--dependency", "nonexistent",
    ])
    assert r.returncode != 0
    assert "not found" in r.stderr


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

def test_task_delete_removes_from_contract(tmp_path: Path) -> None:
    project, contract = _make_contract(tmp_path, [{"id": "to-delete"}])
    r = _run_task([
        "delete",
        "--project", str(project),
        "--id", "to-delete",
    ])
    assert r.returncode == 0, r.stderr
    assert "Deleted task 'to-delete'" in r.stdout
    text = contract.read_text()
    assert "to-delete" not in text


def test_task_delete_not_found_fails(tmp_path: Path) -> None:
    project, _ = _make_contract(tmp_path)
    r = _run_task([
        "delete",
        "--project", str(project),
        "--id", "missing",
    ])
    assert r.returncode != 0
    assert "not found" in r.stderr


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def test_task_status_update_requires_actor_match_owner(tmp_path: Path) -> None:
    project, _ = _make_contract(tmp_path, [{"id": "t1", "owner": "claude-code", "status": "in_progress"}])
    r = _run_task([
        "status",
        "--project", str(project),
        "--id", "t1",
        "--status", "done",
        "--actor", "codex-cli",
        "--summary", "Done by wrong actor",
    ])
    assert r.returncode != 0
    assert "forbidden" in r.stderr


def test_task_status_update_done_requires_summary(tmp_path: Path) -> None:
    project, _ = _make_contract(tmp_path, [{"id": "t2", "owner": "claude-code", "status": "in_progress"}])
    r = _run_task([
        "status",
        "--project", str(project),
        "--id", "t2",
        "--status", "done",
        "--actor", "claude-code",
    ])
    assert r.returncode != 0
    assert "summary" in r.stderr


def test_task_status_update_failed_requires_reason(tmp_path: Path) -> None:
    project, _ = _make_contract(tmp_path, [{"id": "t3", "owner": "claude-code", "status": "in_progress"}])
    r = _run_task([
        "status",
        "--project", str(project),
        "--id", "t3",
        "--status", "failed",
        "--actor", "claude-code",
    ])
    assert r.returncode != 0
    assert "reason" in r.stderr


def test_task_status_update_checks_dependency(tmp_path: Path) -> None:
    project, _ = _make_contract(tmp_path, [
        {"id": "blocker", "status": "todo"},
        {"id": "dependent", "status": "todo", "dependency": "blocker"},
    ])
    r = _run_task([
        "status",
        "--project", str(project),
        "--id", "dependent",
        "--status", "in_progress",
        "--actor", "claude-code",
        "--summary", "Starting work",
    ])
    assert r.returncode != 0
    assert "blocked" in r.stderr


def test_task_status_update_succeeds(tmp_path: Path) -> None:
    project, contract = _make_contract(tmp_path, [{"id": "t4", "owner": "claude-code", "status": "todo"}])
    r = _run_task([
        "status",
        "--project", str(project),
        "--id", "t4",
        "--status", "in_progress",
        "--actor", "claude-code",
        "--summary", "Working on it",
    ])
    assert r.returncode == 0, r.stderr
    assert "Updated task 't4' status=in_progress by actor=claude-code" in r.stdout
    text = contract.read_text()
    assert "status: in_progress" in text


def test_task_status_update_done_with_dep_done(tmp_path: Path) -> None:
    project, contract = _make_contract(tmp_path, [
        {"id": "blocker", "status": "done"},
        {"id": "dependent", "status": "todo", "dependency": "blocker"},
    ])
    r = _run_task([
        "status",
        "--project", str(project),
        "--id", "dependent",
        "--status", "in_progress",
        "--actor", "claude-code",
        "--summary", "Dependency cleared",
    ])
    assert r.returncode == 0, r.stderr
    text = contract.read_text()
    assert "status: in_progress" in text
