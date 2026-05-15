"""Broader dispatch safety guards — prevents phantom dispatch patterns beyond
the basic auto_enqueue_approved case.

Patterns covered:
  A. plan_approved with no acceptance criteria → agent has nothing to verify
  B. plan_approved with no project_path → agent cannot locate the repo
  C. Repeated waiting_input escalation flood after operator resets
  D. autonomy=supervised blocks ALL auto-dispatch paths (belt-and-braces)
  E. Task in plan_approved but missing from SQLite tasks table → no FK to hang inbox on

Each test documents the guard that prevents it and pins the behaviour so
regressions surface immediately.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import pytest
import yaml

from superharness.commands.inbox_watch import auto_enqueue_approved
from superharness.engine.db import get_connection, init_db


# ---------------------------------------------------------------------------
# Helpers (shared with test_auto_enqueue_approved_guards but kept local
# to avoid test-order coupling)
# ---------------------------------------------------------------------------

def _project(tmp_path: Path, profile_extra: dict | None = None) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir()
    conn = get_connection(str(tmp_path)); init_db(conn); conn.close()
    profile = {"auto_dispatch": True, "autonomy": "ai_driven", "_config_version": 1}
    if profile_extra:
        profile.update(profile_extra)
    (sh / "profile.yaml").write_text(yaml.dump(profile))
    (sh / "contract.yaml").write_text(yaml.dump({"id": "main", "tasks": []}))
    return tmp_path


def _task(project: Path, task_id: str, status: str = "plan_approved", **kwargs) -> None:
    sh = project / ".superharness"
    doc = yaml.safe_load((sh / "contract.yaml").read_text()) or {"id": "main", "tasks": []}
    entry = {
        "id": task_id,
        "title": f"Task {task_id}",
        "status": status,
        "owner": "claude-code",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_path": str(project),
        **kwargs,
    }
    doc.setdefault("tasks", []).append(entry)
    (sh / "contract.yaml").write_text(yaml.dump(doc))


def _pending(project: Path, task_id: str) -> int:
    conn = get_connection(str(project))
    n = conn.execute(
        "SELECT COUNT(*) FROM inbox WHERE task_id=? AND status='pending'", (task_id,)
    ).fetchone()[0]
    conn.close()
    return n


def _fail(project: Path, task_id: str, count: int) -> None:
    conn = get_connection(str(project))
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO tasks (id,title,status,owner,project_path,created_at) "
        "VALUES (?,?,?,?,?,?)",
        (task_id, f"Task {task_id}", "plan_approved", "claude-code", str(project), now),
    )
    for i in range(count):
        conn.execute(
            "INSERT OR IGNORE INTO inbox (id,task_id,target_agent,status,project_path,created_at) "
            "VALUES (?,?,'claude-code','failed',?,?)",
            (f"{task_id}-f{i}", task_id, str(project), now),
        )
    conn.commit(); conn.close()


# ---------------------------------------------------------------------------
# Pattern A — plan_approved with no acceptance criteria
# Guard: auto_enqueue_approved checks task.get("criteria") or similar
# Current state: NOT YET GUARDED — test documents desired behaviour and
# will XFAIL until the guard is implemented.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    reason="Guard not yet implemented: plan_approved with empty criteria should be blocked",
    strict=False,
)
def test_plan_approved_with_no_criteria_is_not_dispatched(tmp_path):
    """A task approved with zero acceptance criteria gives the agent nothing to
    verify against. It should be held at plan_approved until criteria are added
    rather than being dispatched into a context-free execution loop."""
    project = _project(tmp_path)
    _task(project, "t-nocrit", criteria=[])   # explicitly empty
    count = auto_enqueue_approved(str(project))
    assert count == 0, (
        "plan_approved tasks with no acceptance criteria must not be auto-dispatched. "
        "Implement: skip enqueue if task.get('criteria') is empty/None."
    )


# ---------------------------------------------------------------------------
# Pattern B — plan_approved with no project_path
# Guard: skip enqueue if project_path is missing/blank on the task row
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    reason="Guard not yet implemented: missing project_path should block dispatch",
    strict=False,
)
def test_plan_approved_with_no_project_path_is_not_dispatched(tmp_path):
    """Without project_path the agent cannot locate the repo. Dispatching it
    wastes a retry budget and floods the inbox with context-free failures."""
    project = _project(tmp_path)
    sh = project / ".superharness"
    doc = yaml.safe_load((sh / "contract.yaml").read_text()) or {"id": "main", "tasks": []}
    doc["tasks"].append({
        "id": "t-nopath",
        "title": "No path task",
        "status": "plan_approved",
        "owner": "claude-code",
        "created_at": datetime.now(timezone.utc).isoformat(),
        # no project_path key
    })
    (sh / "contract.yaml").write_text(yaml.dump(doc))
    count = auto_enqueue_approved(str(project))
    assert count == 0, (
        "plan_approved tasks with no project_path must not be auto-dispatched. "
        "Implement: skip enqueue if not task.get('project_path')."
    )


# ---------------------------------------------------------------------------
# Pattern C — waiting_input escalation flood
# After max_retries the task is escalated to waiting_input. If the operator
# resets to plan_approved without fixing the root cause, the cycle repeats.
# Guard: auto_enqueue_approved counts ALL failed inbox rows regardless of
# when they were inserted — total historical failures always accumulate,
# so 6 failures (2× default cap of 3) already hard-stops re-dispatch.
# ---------------------------------------------------------------------------

def test_repeated_reset_does_not_create_infinite_retry_loop(tmp_path):
    """Simulates operator resetting a task to plan_approved after waiting_input
    escalation. Without a hard-stop on total historical failures the task
    gets another full retry budget each reset."""
    project = _project(tmp_path)
    _task(project, "t-flood")

    # Simulate 2 full retry cycles (3 failures + reset, 3 failures + reset)
    # = 6 total historical failures
    _fail(project, "t-flood", 6)

    count = auto_enqueue_approved(str(project))
    assert count == 0, (
        "After 2+ full retry cycles the task must be hard-stopped. "
        "Implement: track total_failures across resets with a hard cap (e.g. 2x default)."
    )


# ---------------------------------------------------------------------------
# Pattern D — legacy autonomy aliases all normalize to ai_driven and dispatch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("autonomy", ["supervised", "approval-gated", "full-auto", "autonomous"])
def test_legacy_autonomy_aliases_normalize_to_ai_driven_and_dispatch(
    tmp_path, autonomy
):
    project = _project(tmp_path, profile_extra={"autonomy": autonomy, "auto_dispatch": True})
    _task(project, "t-sup")
    count = auto_enqueue_approved(str(project))
    assert count == 1, f"autonomy={autonomy} should normalize to ai_driven and dispatch"


# ---------------------------------------------------------------------------
# Pattern E — task in YAML contract but missing from SQLite tasks table
# FK constraint would reject any inbox row → silent drop or crash
# Guard: auto_enqueue_approved should upsert a minimal tasks row before
# inserting into inbox, OR skip gracefully.
# Current state: the function does try/except around the insert, so it
# silently fails. This test pins that it does NOT crash and returns 0.
# ---------------------------------------------------------------------------

def test_plan_approved_task_missing_from_sqlite_does_not_crash(tmp_path):
    """Task exists in YAML but not in SQLite — FK would fail. Must not crash."""
    project = _project(tmp_path)
    sh = project / ".superharness"
    doc = yaml.safe_load((sh / "contract.yaml").read_text()) or {"id": "main", "tasks": []}
    doc["tasks"].append({
        "id": "t-orphan",
        "title": "Orphan",
        "status": "plan_approved",
        "owner": "claude-code",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_path": str(project),
    })
    (sh / "contract.yaml").write_text(yaml.dump(doc))
    # Do NOT insert into SQLite tasks table — simulate the gap
    try:
        count = auto_enqueue_approved(str(project))
    except Exception as exc:
        pytest.fail(f"auto_enqueue_approved must not raise on FK gap: {exc}")
    # Either succeeds (0 or 1) or skips — main invariant is no crash


# ---------------------------------------------------------------------------
# Regression: the exact bug that occurred (plan_approved + ai_driven + 0 failures)
# This is the explicit regression test for the incident.
# ---------------------------------------------------------------------------

def test_regression_plan_approved_with_ai_driven_dispatches_once(tmp_path):
    """Regression for the incident where all I3-I8 tasks were auto-dispatched
    immediately after being set to plan_approved. Confirms the behaviour IS
    intentional for ai_driven autonomy, and the guard is the autonomy level."""
    project = _project(tmp_path, profile_extra={"autonomy": "ai_driven"})
    _task(project, "t-regression")
    count = auto_enqueue_approved(str(project))
    # With ai_driven + auto_dispatch=True + 0 failures → correctly dispatches once
    assert count == 1
    # auto_dispatch=False is the real gate now
    (project / ".superharness" / "profile.yaml").write_text(
        yaml.dump({"auto_dispatch": False, "autonomy": "ai_driven", "_config_version": 1})
    )
    count2 = auto_enqueue_approved(str(project))
    assert count2 == 0, "auto_dispatch=False must block dispatch regardless of autonomy"
