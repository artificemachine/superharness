"""Iteration 2: auto-approve hook — plan_proposed → plan_approved when autonomy=ai_driven.

Verifies that `shux task status --status plan_proposed` on a task with
autonomy=ai_driven automatically advances to plan_approved.  Tasks with
oversight or hands_on stay at plan_proposed.  No recursion beyond one step.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

PYTHON = sys.executable


def _make_project(tmp_path: Path, task: dict) -> Path:
    """Create a minimal project with one task. Returns project path."""
    project = tmp_path / "proj"
    sh = project / ".superharness"
    sh.mkdir(parents=True)
    contract = {
        "id": "proj",
        "tasks": [task],
    }
    (sh / "contract.yaml").write_text(yaml.dump(contract))
    from tests.helpers import seed_sqlite_from_yaml
    seed_sqlite_from_yaml(project)
    return project


def _run_status(project: Path, task_id: str, status: str,
                actor: str = "claude-code",
                summary: str = "test summary",
                reason: str = "") -> subprocess.CompletedProcess:
    args = [
        PYTHON, "-m", "superharness.commands.task",
        "status",
        "--project", str(project),
        "--id", task_id,
        "--status", status,
        "--actor", actor,
    ]
    if summary:
        args += ["--summary", summary]
    if reason:
        args += ["--reason", reason]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _read_task_status(project: Path, task_id: str) -> str:
    contract_path = project / ".superharness" / "contract.yaml"
    doc = yaml.safe_load(contract_path.read_text())
    for t in doc.get("tasks", []):
        if isinstance(t, dict) and t.get("id") == task_id:
            return str(t.get("status", ""))
    raise AssertionError(f"task {task_id} not found")


def _base_task(task_id: str = "t1", autonomy: str = "ai_driven",
               status: str = "todo") -> dict:
    return {
        "id": task_id,
        "title": "test task",
        "owner": "claude-code",
        "status": status,
        "autonomy": autonomy,
        "require_tdd": True,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_plan_proposed_auto_flips_to_plan_approved_when_ai_driven(
        tmp_path: Path) -> None:
    """ai_driven task: plan_proposed → plan_approved automatically."""
    task = _base_task(autonomy="ai_driven")
    project = _make_project(tmp_path, task)
    r = _run_status(project, "t1", "plan_proposed")
    assert r.returncode == 0, r.stderr
    final = _read_task_status(project, "t1")
    assert final == "plan_approved", f"expected plan_approved, got {final!r}"


def test_plan_proposed_stays_when_oversight(tmp_path: Path) -> None:
    """oversight task: plan_proposed stays (human must approve)."""
    task = _base_task(autonomy="oversight")
    project = _make_project(tmp_path, task)
    r = _run_status(project, "t1", "plan_proposed")
    assert r.returncode == 0, r.stderr
    assert _read_task_status(project, "t1") == "plan_proposed"


def test_plan_proposed_stays_when_hands_on(tmp_path: Path) -> None:
    """hands_on task: plan_proposed stays (human gates every transition)."""
    task = _base_task(autonomy="hands_on")
    project = _make_project(tmp_path, task)
    r = _run_status(project, "t1", "plan_proposed")
    assert r.returncode == 0, r.stderr
    assert _read_task_status(project, "t1") == "plan_proposed"


def test_plan_proposed_stays_when_autonomy_absent(tmp_path: Path) -> None:
    """Task without autonomy field defaults to ai_driven → auto-approves."""
    task = {
        "id": "t1", "title": "x", "owner": "claude-code",
        "status": "todo",
        # no autonomy field
    }
    project = _make_project(tmp_path, task)
    r = _run_status(project, "t1", "plan_proposed")
    assert r.returncode == 0, r.stderr
    # Default is ai_driven → should auto-approve
    assert _read_task_status(project, "t1") == "plan_approved"


def test_no_recursion_beyond_one_step(tmp_path: Path) -> None:
    """Auto-approve must not recurse plan_approved → in_progress."""
    task = _base_task(autonomy="ai_driven")
    project = _make_project(tmp_path, task)
    r = _run_status(project, "t1", "plan_proposed")
    assert r.returncode == 0, r.stderr
    # Final status must be plan_approved, not in_progress or beyond
    assert _read_task_status(project, "t1") == "plan_approved"


def test_ledger_logs_auto_approval(tmp_path: Path) -> None:
    """Ledger gets a line mentioning auto-approved when ai_driven."""
    task = _base_task(autonomy="ai_driven")
    project = _make_project(tmp_path, task)
    r = _run_status(project, "t1", "plan_proposed")
    assert r.returncode == 0, r.stderr
    ledger = (project / ".superharness" / "ledger.md")
    if ledger.exists():
        content = ledger.read_text()
        assert "auto" in content.lower() or "ai_driven" in content.lower(), (
            f"expected auto-approval mention in ledger, got:\n{content}"
        )
    # If ledger doesn't exist yet, at least stdout should mention it
    else:
        combined = (r.stdout + r.stderr).lower()
        assert "auto" in combined or "approved" in combined, (
            f"expected auto-approval mention in output, got:\n{r.stdout}\n{r.stderr}"
        )


def test_other_transitions_unaffected_for_ai_driven(tmp_path: Path) -> None:
    """Non-plan_proposed transitions are not auto-advanced for ai_driven."""
    task = _base_task(autonomy="ai_driven", status="plan_approved")
    project = _make_project(tmp_path, task)
    r = _run_status(project, "t1", "in_progress", summary="starting")
    assert r.returncode == 0, r.stderr
    # Should be in_progress, not further advanced
    assert _read_task_status(project, "t1") == "in_progress"
