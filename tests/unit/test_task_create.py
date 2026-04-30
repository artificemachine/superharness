"""Tests for superharness.commands.task (Python module).

Tests create/delete/status operations via subprocess (python3 -m superharness.commands.task).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

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

    # Seed SQLite so state_reader (sqlite_only) finds the tasks.
    from superharness.engine.db import get_connection, init_db
    from superharness.engine.contract_io import _task_row_from_dict
    from superharness.engine import tasks_dao
    conn = get_connection(str(project))
    init_db(conn)
    for t in tasks:
        t["project_path"] = project.as_posix()
        tasks_dao.upsert(conn, _task_row_from_dict(t, str(project), "2026-01-01T00:00:00Z"))
    conn.commit()
    conn.close()

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
    assert "owner must be one of:" in r.stderr


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
    assert "dependency" in r.stdout or "blocked_by" in r.stdout
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


# ---------------------------------------------------------------------------
# tdd block
# ---------------------------------------------------------------------------

def test_task_create_with_tdd_block(tmp_path: Path) -> None:
    """task create with --tdd-red/green/refactor writes tdd block to contract."""
    project, contract = _make_contract(tmp_path)
    r = _run_task([
        "create",
        "--project", str(project),
        "--id", "feat.tdd-task",
        "--title", "TDD feature",
        "--owner", "claude-code",
        "--tdd-red", "write failing test for X",
        "--tdd-green", "minimal code to pass X",
        "--tdd-refactor", "extract helper, no new behaviour",
    ])
    assert r.returncode == 0, r.stderr
    data = yaml.safe_load(contract.read_text())
    task = next(t for t in data["tasks"] if t["id"] == "feat.tdd-task")
    assert "tdd" in task
    assert task["tdd"]["red"] == "write failing test for X"
    assert task["tdd"]["green"] == "minimal code to pass X"
    assert task["tdd"]["refactor"] == "extract helper, no new behaviour"


def test_task_create_without_tdd_has_no_tdd_key(tmp_path: Path) -> None:
    """task create without --tdd-* flags omits tdd key from contract."""
    project, contract = _make_contract(tmp_path)
    r = _run_task([
        "create",
        "--project", str(project),
        "--id", "feat.no-tdd",
        "--title", "No TDD",
        "--owner", "claude-code",
    ])
    assert r.returncode == 0, r.stderr
    data = yaml.safe_load(contract.read_text())
    task = next(t for t in data["tasks"] if t["id"] == "feat.no-tdd")
    assert "tdd" not in task


def test_task_create_tdd_partial_is_accepted(tmp_path: Path) -> None:
    """task create with only some tdd flags still writes what's provided."""
    project, contract = _make_contract(tmp_path)
    r = _run_task([
        "create",
        "--project", str(project),
        "--id", "feat.partial-tdd",
        "--title", "Partial TDD",
        "--owner", "claude-code",
        "--tdd-red", "write the failing test",
    ])
    assert r.returncode == 0, r.stderr
    data = yaml.safe_load(contract.read_text())
    task = next(t for t in data["tasks"] if t["id"] == "feat.partial-tdd")
    assert "tdd" in task
    assert task["tdd"]["red"] == "write the failing test"
    assert "green" not in task["tdd"]
    assert "refactor" not in task["tdd"]


# ---------------------------------------------------------------------------
# Full lifecycle status vocabulary
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [
    "plan_proposed", "plan_approved", "report_ready", "review_passed", "review_failed",
])
def test_task_status_accepts_full_lifecycle_statuses(tmp_path: Path, status: str) -> None:
    """task status must accept all lifecycle statuses, not just the legacy subset."""
    project, _ = _make_contract(tmp_path, [{"id": "t-lc", "owner": "claude-code", "status": "todo"}])
    extra = ["--summary", "moving along"] if status not in ("failed", "stopped") else ["--reason", "blocked"]
    r = _run_task([
        "status",
        "--project", str(project),
        "--id", "t-lc",
        "--status", status,
        "--actor", "claude-code",
    ] + extra)
    assert r.returncode == 0, f"status '{status}' rejected: {r.stderr}"
    assert status in r.stdout


def test_task_plan_approved_warns_large_scope(tmp_path: Path) -> None:
    """plan_approved warns when acceptance_criteria > 3."""
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text(
        "id: test-contract\n"
        "tasks:\n"
        "  - id: big-task\n"
        "    title: Big task\n"
        "    owner: claude-code\n"
        "    status: plan_proposed\n"
        f"    project_path: '{project.as_posix()}'\n"
        "    acceptance_criteria:\n"
        "      - criterion 1\n"
        "      - criterion 2\n"
        "      - criterion 3\n"
        "      - criterion 4\n"
    )
    r = _run_task([
        "status",
        "--project", str(project),
        "--id", "big-task",
        "--status", "plan_approved",
        "--actor", "claude-code",
    ])
    assert r.returncode == 0, r.stderr
    assert "Scope warning" in r.stderr
    assert "4 acceptance criteria" in r.stderr


def test_task_plan_approved_no_warning_small_scope(tmp_path: Path) -> None:
    """plan_approved does not warn when acceptance_criteria <= 3."""
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text(
        "id: test-contract\n"
        "tasks:\n"
        "  - id: small-task\n"
        "    title: Small task\n"
        "    owner: claude-code\n"
        "    status: plan_proposed\n"
        f"    project_path: '{project.as_posix()}'\n"
        "    acceptance_criteria:\n"
        "      - criterion 1\n"
        "      - criterion 2\n"
    )
    r = _run_task([
        "status",
        "--project", str(project),
        "--id", "small-task",
        "--status", "plan_approved",
        "--actor", "claude-code",
    ])
    assert r.returncode == 0, r.stderr
    assert "Scope warning" not in r.stderr


def test_task_status_rejects_unknown_status(tmp_path: Path) -> None:
    """task status must reject statuses not in the vocabulary."""
    project, _ = _make_contract(tmp_path, [{"id": "t-bad", "owner": "claude-code", "status": "todo"}])
    r = _run_task([
        "status",
        "--project", str(project),
        "--id", "t-bad",
        "--status", "flying",
        "--actor", "claude-code",
        "--summary", "invalid",
    ])
    assert r.returncode != 0
    assert "status must be" in r.stderr


def test_task_create_autogenerates_id(tmp_path: Path) -> None:
    """--id is optional; task create auto-generates a t-XXXXXX id when omitted."""
    project, contract_file = _make_contract(tmp_path)
    r = _run_task([
        "create",
        "--project", str(project),
        "--title", "Auto ID task",
        "--owner", "claude-code",
    ])
    assert r.returncode == 0, r.stderr
    doc = yaml.safe_load(contract_file.read_text())
    tasks = doc.get("tasks", [])
    assert len(tasks) == 1
    task_id = tasks[0]["id"]
    assert task_id.startswith("t-"), f"Expected t-XXXXXX, got {task_id!r}"
    assert len(task_id) == 8, f"Expected t-XXXXXX (8 chars), got {task_id!r}"


# ---------------------------------------------------------------------------
# ship_on_complete flag
# ---------------------------------------------------------------------------

def test_task_create_ship_on_complete_writes_flag(tmp_path: Path) -> None:
    project, contract = _make_contract(tmp_path)
    result = _run_task([
        "create", "--project", str(project),
        "--id", "feat.ship-me",
        "--title", "Ship me task",
        "--owner", "claude-code",
        "--ship-on-complete",
    ])
    assert result.returncode == 0, result.stderr
    doc = yaml.safe_load(contract.read_text()) or {}
    task = next(t for t in doc.get("tasks", []) if t["id"] == "feat.ship-me")
    assert task.get("ship_on_complete") is True


def test_task_create_ship_on_complete_defaults_absent(tmp_path: Path) -> None:
    """Without --ship-on-complete the field is not written (stays schema default)."""
    project, contract = _make_contract(tmp_path)
    result = _run_task([
        "create", "--project", str(project),
        "--id", "feat.normal",
        "--title", "Normal task",
        "--owner", "claude-code",
    ])
    assert result.returncode == 0, result.stderr
    doc = yaml.safe_load(contract.read_text()) or {}
    task = next(t for t in doc.get("tasks", []) if t["id"] == "feat.normal")
    assert not task.get("ship_on_complete")
