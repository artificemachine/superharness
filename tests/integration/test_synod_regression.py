"""
Regression: synod project failure 2026-04-15.

shux delegate iter-0-red --to claude-code succeeded (enqueued) but the launcher
rejected it 12s later: "blocked: task 'iter-0-red' status is 'todo'".  Three
wasted launcher cycles followed (retry_count 1/3, 2/3, 3/3).

Root cause: inbox_enqueue.py accepted todo+implementation tasks that
delegate.py gate-4 would always reject.

Fix: inbox_enqueue._validate_contract now mirrors delegate's lifecycle gate.
These tests assert the pre-write rejection so inbox.yaml is never written.
"""
from __future__ import annotations

import sys
import yaml
import pytest
from pathlib import Path

from tests.helpers import REPO_ROOT

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")

_CLI = [sys.executable, "-m", "superharness.commands.inbox_enqueue"]


def _run(args: list[str], *, project: Path) -> "subprocess.CompletedProcess[str]":
    import subprocess, os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        _CLI + args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _make_project(tmp_path: Path, name: str) -> Path:
    project = tmp_path / name
    (project / ".superharness").mkdir(parents=True)
    return project


def _write_contract(project: Path, task: dict) -> None:
    contract = {
        "id": "test-contract",
        "status": "active",
        "tasks": [task],
    }
    (project / ".superharness" / "contract.yaml").write_text(yaml.dump(contract))


# ── core regression ──────────────────────────────────────────────────────────

def test_todo_task_cannot_be_enqueued_for_implementation(tmp_path: Path) -> None:
    """Exact synod failure: todo + implementation → rejected before inbox.yaml written."""
    project = _make_project(tmp_path, "synod-replica")
    _write_contract(project, {
        "id": "iter-0-red",
        "title": "TDD red phase",
        "status": "todo",
        "workflow": "implementation",
        "owner": "claude-code",
        "project_path": str(project.resolve()),
    })

    result = _run(
        ["--project", str(project), "--to", "claude-code", "--task", "iter-0-red"],
        project=project,
    )

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "todo" in combined
    assert "iter-0-red" in combined
    inbox = project / ".superharness" / "inbox.yaml"
    assert not inbox.exists(), "inbox.yaml must not be written when gate rejects"


def test_rejected_message_surfaces_hint(tmp_path: Path) -> None:
    """Rejection message tells the user how to unblock (--plan-only)."""
    project = _make_project(tmp_path, "synod-hint")
    _write_contract(project, {
        "id": "iter-0",
        "title": "Iteration 0",
        "status": "todo",
        "workflow": "implementation",
        "owner": "claude-code",
        "project_path": str(project.resolve()),
    })

    result = _run(
        ["--project", str(project), "--to", "claude-code", "--task", "iter-0"],
        project=project,
    )

    assert result.returncode == 1
    assert "--plan-only" in result.stdout + result.stderr


def test_plan_only_unblocks_todo_implementation(tmp_path: Path) -> None:
    """--plan-only is the escape hatch that the synod session needed."""
    project = _make_project(tmp_path, "synod-plan-only")
    _write_contract(project, {
        "id": "iter-0-red",
        "title": "TDD red phase",
        "status": "todo",
        "workflow": "implementation",
        "owner": "claude-code",
        "project_path": str(project.resolve()),
    })

    result = _run(
        ["--project", str(project), "--to", "claude-code", "--task", "iter-0-red", "--plan-only"],
        project=project,
    )

    assert result.returncode == 0, result.stderr
    inbox = project / ".superharness" / "inbox.yaml"
    assert inbox.exists()
    data = yaml.safe_load(inbox.read_text()) or []
    items = [x for x in data if isinstance(x, dict)]
    assert len(items) == 1
    assert items[0].get("plan_only") is True


def test_owner_mismatch_silent_accept_is_gone(tmp_path: Path) -> None:
    """Defect B: silently accepting --to that contradicts owner is fixed."""
    project = _make_project(tmp_path, "synod-owner")
    _write_contract(project, {
        "id": "iter-0-red",
        "title": "TDD red phase",
        "status": "plan_approved",
        "workflow": "implementation",
        "owner": "codex-cli",
        "project_path": str(project.resolve()),
    })

    result = _run(
        ["--project", str(project), "--to", "claude-code", "--task", "iter-0-red"],
        project=project,
    )

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "codex-cli" in combined
    assert "claude-code" in combined
    inbox = project / ".superharness" / "inbox.yaml"
    assert not inbox.exists()
