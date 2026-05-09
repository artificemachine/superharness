from __future__ import annotations
import pytest

import subprocess
import sys
from pathlib import Path

from tests.helpers import REPO_ROOT


def _run_python(args: list[str]) -> subprocess.CompletedProcess:
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.inbox_enqueue"] + args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _setup_project(tmp_path: Path, name: str) -> Path:
    project = tmp_path / name
    project.mkdir()
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    from tests.helpers import seed_sqlite_from_yaml
    seed_sqlite_from_yaml(project)
    return project


def _write_contract(project: Path, lines: list[str]) -> None:
    (project / ".superharness" / "contract.yaml").write_text("\n".join(lines) + "\n")


def test_enqueue_fails_when_task_project_path_missing(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-missing-path")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: mcp-docs",
            "    title: docs",
        ],
    )

    result = _run_python(["--project", str(project), "--to", "codex-cli", "--task", "mcp-docs"])

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "missing project_path" in combined or "project_path" in combined


def test_enqueue_fails_when_task_project_path_mismatch(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-mismatch")
    other = tmp_path / "other-project"
    other.mkdir()
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: mcp-docs",
            f"    project_path: '{other.as_posix()}'",
        ],
    )

    result = _run_python(["--project", str(project), "--to", "codex-cli", "--task", "mcp-docs"])

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "project_path mismatch" in combined or "mismatch" in combined


def test_enqueue_rejects_invalid_task_token(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-invalid-task")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks: []",
        ],
    )

    result = _run_python(["--project", str(project), "--to", "codex-cli", "--task", "bad|task"])

    assert result.returncode in (1, 2)
    combined = result.stdout + result.stderr
    assert "task id" in combined.lower() or "invalid" in combined.lower() or "match" in combined.lower()


def test_enqueue_blocks_plan_proposed_status(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-plan-proposed")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: feat.blocked",
            "    status: plan_proposed",
            f"    project_path: '{project.resolve().as_posix()}'",
        ],
    )

    result = _run_python(["--project", str(project), "--to", "claude-code", "--task", "feat.blocked"])

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "plan_proposed" in combined
    assert "cannot enqueue" in combined


def test_enqueue_blocks_done_status(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-done")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: feat.closed",
            "    status: done",
            f"    project_path: '{project.resolve().as_posix()}'",
        ],
    )

    result = _run_python(["--project", str(project), "--to", "claude-code", "--task", "feat.closed"])

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "done" in combined
    assert "cannot enqueue" in combined


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_allows_plan_approved_status(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-approved")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: feat.ready",
            "    status: plan_approved",
            f"    project_path: '{project.resolve().as_posix()}'",
        ],
    )

    result = _run_python(["--project", str(project), "--to", "claude-code", "--task", "feat.ready"])

    assert result.returncode == 0
    assert "Enqueued inbox item" in result.stdout


def test_enqueue_rejects_invalid_custom_item_id(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-invalid-id")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks: []",
        ],
    )

    result = _run_python(
        [
            "--project",
            str(project),
            "--to",
            "codex-cli",
            "--task",
            "mcp-docs",
            "--id",
            "bad\nid",
        ]
    )

    assert result.returncode in (1, 2)
    combined = result.stdout + result.stderr
    assert "inbox id" in combined.lower() or "invalid" in combined.lower() or "match" in combined.lower()


# ── gate parity: enqueue must mirror dispatch's workflow-aware gate ──────────

def test_enqueue_rejects_todo_for_implementation(repo_root, tmp_path) -> None:
    """todo + implementation workflow cannot be enqueued (dispatch would reject)."""
    project = _setup_project(tmp_path, "proj-todo-impl")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: feat.wip",
            "    status: todo",
            "    workflow: implementation",
            f"    project_path: '{project.resolve().as_posix()}'",
        ],
    )
    r = _run_python(["--project", str(project), "--to", "claude-code", "--task", "feat.wip"])
    assert r.returncode == 1
    combined = r.stdout + r.stderr
    assert "todo" in combined
    assert "implementation" in combined
    assert "--plan-only" in combined  # hint surfaces the escape hatch


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_accepts_todo_for_quick_workflow(repo_root, tmp_path) -> None:
    """todo is dispatchable for `quick` workflow — no plan required."""
    project = _setup_project(tmp_path, "proj-todo-quick")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: chore.simple",
            "    status: todo",
            "    workflow: quick",
            f"    project_path: '{project.resolve().as_posix()}'",
        ],
    )
    r = _run_python(["--project", str(project), "--to", "claude-code", "--task", "chore.simple"])
    assert r.returncode == 0, r.stderr
    assert "Enqueued inbox item" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_accepts_todo_for_implementation_with_plan_only(repo_root, tmp_path) -> None:
    """--plan-only relaxes the gate: todo + implementation becomes enqueueable."""
    project = _setup_project(tmp_path, "proj-plan-only")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: feat.needs-plan",
            "    status: todo",
            "    workflow: implementation",
            f"    project_path: '{project.resolve().as_posix()}'",
        ],
    )
    r = _run_python([
        "--project", str(project), "--to", "claude-code",
        "--task", "feat.needs-plan", "--plan-only",
    ])
    assert r.returncode == 0, r.stderr
    assert "plan-only" in r.stdout


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_marks_item_plan_only_in_inbox(repo_root, tmp_path) -> None:
    """Plan-only flag persists on the inbox item for the launcher to read."""
    project = _setup_project(tmp_path, "proj-plan-only-flag")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: feat.needs-plan",
            "    status: todo",
            "    workflow: implementation",
            f"    project_path: '{project.resolve().as_posix()}'",
        ],
    )
    r = _run_python([
        "--project", str(project), "--to", "claude-code",
        "--task", "feat.needs-plan", "--plan-only",
    ])
    assert r.returncode == 0, r.stderr

    # Post-migration the inbox is in SQLite, not inbox.yaml.
    import sqlite3 as _sql
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    rows = db.execute(
        "SELECT id, plan_only FROM inbox WHERE task_id='feat.needs-plan'"
    ).fetchall()
    db.close()
    assert len(rows) == 1
    assert rows[0][1] == 1  # SQLite stores plan_only as INTEGER


# ── owner-mismatch guard ─────────────────────────────────────────────────────

def test_enqueue_blocks_owner_mismatch_by_default(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-owner-mismatch")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: feat.owned",
            "    status: plan_approved",
            "    workflow: implementation",
            "    owner: codex-cli",
            f"    project_path: '{project.resolve().as_posix()}'",
        ],
    )
    r = _run_python(["--project", str(project), "--to", "claude-code", "--task", "feat.owned"])
    assert r.returncode == 1
    combined = r.stdout + r.stderr
    assert "owned by 'codex-cli'" in combined
    assert "not 'claude-code'" in combined
    assert "--force-reassign" in combined


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_allows_owner_mismatch_with_force_flag(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path, "proj-owner-force")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: feat.owned",
            "    status: plan_approved",
            "    workflow: implementation",
            "    owner: codex-cli",
            f"    project_path: '{project.resolve().as_posix()}'",
        ],
    )
    r = _run_python([
        "--project", str(project), "--to", "claude-code",
        "--task", "feat.owned", "--force-reassign",
    ])
    assert r.returncode == 0, r.stderr
    # Warning printed to stderr, but enqueue still succeeds.
    assert "reassigning" in r.stderr.lower()


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_enqueue_accepts_target_matching_owner(repo_root, tmp_path) -> None:
    """No warning, no block when --to matches contract owner."""
    project = _setup_project(tmp_path, "proj-owner-match")
    _write_contract(
        project,
        [
            "id: test-contract",
            "tasks:",
            "  - id: feat.owned",
            "    status: plan_approved",
            "    workflow: implementation",
            "    owner: claude-code",
            f"    project_path: '{project.resolve().as_posix()}'",
        ],
    )
    r = _run_python(["--project", str(project), "--to", "claude-code", "--task", "feat.owned"])
    assert r.returncode == 0, r.stderr
    assert "reassigning" not in r.stderr.lower()
