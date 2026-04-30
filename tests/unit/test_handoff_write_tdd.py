"""Iteration 3: TDD enforcement in handoff-write when require_tdd=true.

When a task has require_tdd=true AND workflow in {implementation, review},
shux handoff-write --phase plan rejects handoffs missing any of
tdd.red / tdd.green / tdd.refactor (exit 2).

For other workflows or require_tdd=false, TDD fields remain optional.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml, get_task_from_sqlite

import yaml

PYTHON = sys.executable


def _make_project(tmp_path: Path, task: dict) -> Path:
    project = tmp_path / "proj"
    sh = project / ".superharness"
    sh.mkdir(parents=True)
    (sh / "contract.yaml").write_text(yaml.dump({"id": "proj", "tasks": [task]}))
    seed_sqlite_from_yaml(project)
    return project


def _base_task(workflow: str = "implementation", require_tdd: bool = True) -> dict:
    return {
        "id": "t1",
        "title": "test task",
        "owner": "claude-code",
        "status": "todo",
        "workflow": workflow,
        "require_tdd": require_tdd,
        "autonomy": "oversight",
    }


def _run_handoff(project: Path, *extra: str) -> subprocess.CompletedProcess:
    args = [
        PYTHON, "-m", "superharness.commands.handoff_write",
        "--project", str(project),
        "--task", "t1",
        "--phase", "plan",
        "--from", "claude-code",
        "--to", "owner",
        "--plan", "do the thing",
    ] + list(extra)
    return subprocess.run(args, capture_output=True, text=True, check=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_plan_rejected_when_require_tdd_and_tdd_fields_missing(
        tmp_path: Path) -> None:
    """require_tdd=true + workflow=implementation, no TDD fields → exit 2."""
    project = _make_project(tmp_path, _base_task(workflow="implementation", require_tdd=True))
    r = _run_handoff(project)
    assert r.returncode == 2, f"expected exit 2, got {r.returncode}\n{r.stderr}"
    err = (r.stderr + r.stdout).lower()
    assert "tdd" in err or "red" in err or "green" in err or "refactor" in err, (
        f"expected TDD field mention in error, got: {r.stderr}"
    )


def test_plan_rejected_when_only_some_tdd_fields_present(
        tmp_path: Path) -> None:
    """All three TDD fields required; partial is not enough."""
    project = _make_project(tmp_path, _base_task(workflow="implementation", require_tdd=True))
    # Provide only red — missing green and refactor
    r = _run_handoff(project, "--tdd-red", "write failing test")
    assert r.returncode == 2, f"expected exit 2, got {r.returncode}\n{r.stderr}"


def test_plan_accepted_when_require_tdd_false(tmp_path: Path) -> None:
    """require_tdd=false → plan without TDD fields succeeds."""
    project = _make_project(tmp_path, _base_task(workflow="implementation", require_tdd=False))
    r = _run_handoff(project)
    assert r.returncode == 0, f"expected exit 0, got {r.returncode}\n{r.stderr}"


def test_plan_accepted_when_workflow_is_quick(tmp_path: Path) -> None:
    """workflow=quick, even if require_tdd=true → TDD skipped, plan accepted."""
    project = _make_project(tmp_path, _base_task(workflow="quick", require_tdd=True))
    r = _run_handoff(project)
    assert r.returncode == 0, f"expected exit 0, got {r.returncode}\n{r.stderr}"


def test_plan_accepted_when_workflow_is_discussion(tmp_path: Path) -> None:
    """workflow=discussion → TDD not enforced."""
    project = _make_project(tmp_path, _base_task(workflow="discussion", require_tdd=True))
    r = _run_handoff(project)
    assert r.returncode == 0, f"expected exit 0, got {r.returncode}\n{r.stderr}"


def test_plan_accepted_when_all_tdd_fields_present(tmp_path: Path) -> None:
    """All three TDD fields provided → plan accepted for implementation workflow."""
    project = _make_project(tmp_path, _base_task(workflow="implementation", require_tdd=True))
    r = _run_handoff(project,
                     "--tdd-red", "write failing test",
                     "--tdd-green", "write minimal code",
                     "--tdd-refactor", "clean up")
    assert r.returncode == 0, f"expected exit 0, got {r.returncode}\n{r.stderr}"


def test_review_workflow_also_enforces_tdd(tmp_path: Path) -> None:
    """workflow=review + require_tdd=true → TDD fields required."""
    project = _make_project(tmp_path, _base_task(workflow="review", require_tdd=True))
    r = _run_handoff(project)
    assert r.returncode == 2, f"expected exit 2, got {r.returncode}\n{r.stderr}"


def test_error_message_includes_workflow_name(tmp_path: Path) -> None:
    """Error message mentions the workflow for clarity."""
    project = _make_project(tmp_path, _base_task(workflow="implementation", require_tdd=True))
    r = _run_handoff(project)
    err = (r.stderr + r.stdout).lower()
    assert "implementation" in err or "workflow" in err, (
        f"expected workflow mention in error, got: {r.stderr}"
    )


def test_task_without_require_tdd_uses_safe_default(tmp_path: Path) -> None:
    """Task without require_tdd field → defaults to True → TDD required for implementation."""
    task = {
        "id": "t1", "title": "x", "owner": "claude-code", "status": "todo",
        "workflow": "implementation",
        # no require_tdd field
    }
    project = _make_project(tmp_path, task)
    r = _run_handoff(project)
    assert r.returncode == 2, (
        f"expected exit 2 (default require_tdd=True), got {r.returncode}\n{r.stderr}"
    )
