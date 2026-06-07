"""Tests for auto_enqueue_approved guards — prevents phantom dispatch of
manually-managed tasks that were accidentally set to plan_approved.

Root cause documented: creating tasks with plan_approved + auto_dispatch=True in
profile.yaml causes the watcher to immediately dispatch them. Agents find no
implementation context, exit, and the watcher records failures. After max_retries
the task escalates to waiting_input. Tests here pin the guard behaviours so this
cannot regress silently.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import yaml

from superharness.commands.inbox_watch import auto_enqueue_approved
from superharness.engine.db import get_connection, init_db
from superharness.engine import inbox_dao


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path, profile: dict | None = None) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir()
    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.close()

    default_profile = {
        "auto_dispatch": True,
        "autonomy": "ai_driven",
        "_config_version": 1,
    }
    if profile is not None:
        default_profile.update(profile)
    (sh / "profile.yaml").write_text(yaml.dump(default_profile))

    contract = {
        "id": "main",
        "tasks": [],
    }
    (sh / "contract.yaml").write_text(yaml.dump(contract))
    return tmp_path


def _add_task(project: Path, task_id: str, status: str, **kwargs) -> None:
    sh = project / ".superharness"
    doc = yaml.safe_load((sh / "contract.yaml").read_text()) or {"id": "main", "tasks": []}
    doc.setdefault("tasks", []).append({
        "id": task_id,
        "title": f"Task {task_id}",
        "status": status,
        "owner": "claude-code",
        "created_at": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    })
    (sh / "contract.yaml").write_text(yaml.dump(doc))


def _inbox_pending_count(project: Path, task_id: str) -> int:
    conn = get_connection(str(project))
    rows = conn.execute(
        "SELECT COUNT(*) FROM inbox WHERE task_id=? AND status='pending'",
        (task_id,),
    ).fetchone()
    conn.close()
    return rows[0]


def _set_inbox_failures(project: Path, task_id: str, count: int) -> None:
    """Insert `count` failed inbox rows to simulate exhausted retries.
    Also ensures a tasks row exists (required by FK constraint).
    """
    conn = get_connection(str(project))
    now = datetime.now(timezone.utc).isoformat()
    # Ensure task row exists for FK
    conn.execute(
        "INSERT OR IGNORE INTO tasks (id, title, status, owner, project_path, created_at) "
        "VALUES (?, ?, 'plan_approved', 'claude-code', ?, ?)",
        (task_id, f"Task {task_id}", str(project), now),
    )
    for i in range(count):
        conn.execute(
            "INSERT OR IGNORE INTO inbox (id, task_id, target_agent, status, project_path, created_at) "
            "VALUES (?, ?, 'claude-code', 'failed', ?, ?)",
            (f"auto-{task_id}-fail{i}", task_id, str(project), now),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Guard 1: auto_dispatch=False blocks all enqueuing
# ---------------------------------------------------------------------------

def test_auto_enqueue_skipped_when_auto_dispatch_false(tmp_path):
    project = _make_project(tmp_path, profile={"auto_dispatch": False})
    _add_task(project, "t-test01", "plan_approved")
    count = auto_enqueue_approved(str(project))
    assert count == 0
    assert _inbox_pending_count(project, "t-test01") == 0


# ---------------------------------------------------------------------------
# Guard 2: legacy autonomy aliases normalize to ai_driven and dispatch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("autonomy", ["approval-gated", "full-auto", "autonomous"])
def test_legacy_autonomy_aliases_normalize_and_dispatch(tmp_path, autonomy):
    # "supervised" is intentionally excluded: it is a distinct mode, not an alias for ai_driven
    project = _make_project(tmp_path, profile={"auto_dispatch": True, "autonomy": autonomy})
    _add_task(project, "t-test02", "plan_approved")
    count = auto_enqueue_approved(str(project))
    assert count == 1, f"autonomy={autonomy} should normalize to ai_driven and dispatch"


def test_supervised_autonomy_does_not_auto_dispatch(tmp_path):
    """supervised mode preserves human oversight — auto_enqueue must not dispatch."""
    project = _make_project(tmp_path, profile={"auto_dispatch": True, "autonomy": "supervised"})
    _add_task(project, "t-supervised", "plan_approved")
    count = auto_enqueue_approved(str(project))
    assert count == 0, "supervised autonomy must not auto-dispatch (distinct from ai_driven)"


# ---------------------------------------------------------------------------
# Guard 3: plan_proposed is NEVER enqueued (only plan_approved is)
# ---------------------------------------------------------------------------

def test_auto_enqueue_ignores_plan_proposed(tmp_path):
    project = _make_project(tmp_path)
    _add_task(project, "t-test03", "plan_proposed")
    count = auto_enqueue_approved(str(project))
    assert count == 0
    assert _inbox_pending_count(project, "t-test03") == 0


def test_auto_enqueue_ignores_todo(tmp_path):
    project = _make_project(tmp_path)
    _add_task(project, "t-test04", "todo")
    count = auto_enqueue_approved(str(project))
    assert count == 0


def test_auto_enqueue_ignores_report_ready(tmp_path):
    project = _make_project(tmp_path)
    _add_task(project, "t-test05", "report_ready")
    count = auto_enqueue_approved(str(project))
    assert count == 0


# ---------------------------------------------------------------------------
# Guard 4: max_retries cap stops re-enqueueing after N failures
# ---------------------------------------------------------------------------

def test_auto_enqueue_stops_after_default_max_retries(tmp_path):
    """After 3 failures the task must NOT be re-enqueued (default max_retries=3)."""
    project = _make_project(tmp_path)
    _add_task(project, "t-test06", "plan_approved")
    _set_inbox_failures(project, "t-test06", 3)  # exhausted
    count = auto_enqueue_approved(str(project))
    assert count == 0
    assert _inbox_pending_count(project, "t-test06") == 0


def test_auto_enqueue_two_failures_below_default_cap_still_retries(tmp_path):
    """2 failures < default cap of 3 — task should still be re-enqueued."""
    project = _make_project(tmp_path)
    _add_task(project, "t-test07", "plan_approved")
    _set_inbox_failures(project, "t-test07", 2)  # 2 < 3 → still allowed
    count = auto_enqueue_approved(str(project))
    assert count == 1


# NOTE: max_retries is read from the SQLite tasks table which currently has no
# max_retries column — task.get("max_retries") returns None and the default of 3
# is always used. If per-task max_retries is added to the schema, add a test here.


def test_auto_enqueue_allows_one_attempt_before_cap(tmp_path):
    """Fresh task with 0 failures and plan_approved IS enqueued once."""
    project = _make_project(tmp_path)
    _add_task(project, "t-test08", "plan_approved")
    count = auto_enqueue_approved(str(project))
    assert count == 1
    assert _inbox_pending_count(project, "t-test08") == 1


# ---------------------------------------------------------------------------
# Guard 5: missing profile.yaml blocks enqueuing
# ---------------------------------------------------------------------------

def test_auto_enqueue_skipped_when_no_profile(tmp_path):
    sh = tmp_path / ".superharness"
    sh.mkdir()
    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.close()
    (sh / "contract.yaml").write_text(yaml.dump({"id": "main", "tasks": [
        {"id": "t-noprofile", "status": "plan_approved", "owner": "claude-code",
         "created_at": datetime.now(timezone.utc).isoformat()}
    ]}))
    # No profile.yaml — should not enqueue
    count = auto_enqueue_approved(str(tmp_path))
    assert count == 0


# ---------------------------------------------------------------------------
# Guard 6: already-active task is not double-enqueued
# ---------------------------------------------------------------------------

def test_auto_enqueue_does_not_double_enqueue_active_task(tmp_path):
    project = _make_project(tmp_path)
    _add_task(project, "t-test09", "plan_approved")
    # First enqueue
    auto_enqueue_approved(str(project))
    assert _inbox_pending_count(project, "t-test09") == 1
    # Second call — task already active in inbox
    count = auto_enqueue_approved(str(project))
    assert count == 0
    assert _inbox_pending_count(project, "t-test09") == 1  # still exactly 1


# ---------------------------------------------------------------------------
# Guard 7: unsatisfied blocked_by dependency blocks enqueue
# ---------------------------------------------------------------------------

def test_auto_enqueue_respects_blocked_by_dependency(tmp_path):
    """plan_approved task with unresolved blocked_by must NOT be dispatched."""
    project = _make_project(tmp_path)
    _add_task(project, "t-dep01", "todo")        # blocker — not done
    _add_task(project, "t-dep02", "plan_approved", blocked_by="t-dep01")
    count = auto_enqueue_approved(str(project))
    assert count == 0
    assert _inbox_pending_count(project, "t-dep02") == 0


def test_auto_enqueue_dispatches_when_dependency_satisfied(tmp_path):
    """plan_approved task whose blocker is done IS dispatched."""
    project = _make_project(tmp_path)
    _add_task(project, "t-dep03", "done")        # blocker satisfied
    _add_task(project, "t-dep04", "plan_approved", blocked_by="t-dep03")
    count = auto_enqueue_approved(str(project))
    assert count == 1
    assert _inbox_pending_count(project, "t-dep04") == 1
