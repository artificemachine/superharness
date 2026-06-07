"""Iter 10 RED: lifecycle rules for plan-state timeouts.

Verifies that plan_approved/plan_proposed/pending_user_approval tasks
are auto-recovered when they exceed their timeout.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _now_iso(offset_minutes: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _setup_project(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    harness = tmp_path / ".superharness"
    harness.mkdir()
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(tmp_path))
    init_db(conn)
    return tmp_path, conn


def _insert_task(conn: sqlite3.Connection, task_id: str, status: str,
                 timestamp_field: str, timestamp_value: str) -> None:
    conn.execute(
        f"INSERT INTO tasks (id, title, owner, status, created_at, updated_at, "
        f"{timestamp_field}, acceptance_criteria, test_types, out_of_scope, definition_of_done) "
        f"VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (task_id, f"Task {task_id}", "claude-code", status,
         _now_iso(-300), _now_iso(-300), timestamp_value, "[]", "[]", "[]", "[]"),
    )
    conn.commit()


# ── Smoke ─────────────────────────────────────────────────────────────────────

def test_lifecycle_rules_importable():
    from superharness.engine.lifecycle_rules import LIFECYCLE_RULES, LifecycleRule
    assert isinstance(LIFECYCLE_RULES, list)
    assert len(LIFECYCLE_RULES) > 0


def test_reconcile_lifecycle_importable():
    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    assert callable(reconcile_lifecycle)


# ── Iter 10 RED: plan_approved timeout rule exists ────────────────────────────

def test_plan_approved_rule_in_lifecycle_rules():
    """A LifecycleRule for plan_approved must exist — tasks stuck awaiting dispatch must auto-recover.

    RED: No plan_approved rule in LIFECYCLE_RULES. Test fails until the rule is added.
    """
    from superharness.engine.lifecycle_rules import LIFECYCLE_RULES
    states = {r.state for r in LIFECYCLE_RULES}
    assert "plan_approved" in states, (
        "LIFECYCLE_RULES must include a rule for 'plan_approved'. "
        "Tasks stuck in plan_approved (dispatched but agent never picks up) must auto-fail."
    )


def test_plan_proposed_rule_in_lifecycle_rules():
    """A LifecycleRule for plan_proposed must exist — unanswered plan proposals must time out.

    RED: No plan_proposed rule in LIFECYCLE_RULES.
    """
    from superharness.engine.lifecycle_rules import LIFECYCLE_RULES
    states = {r.state for r in LIFECYCLE_RULES}
    assert "plan_proposed" in states, (
        "LIFECYCLE_RULES must include a rule for 'plan_proposed'. "
        "Tasks awaiting operator approval must auto-fail after the timeout."
    )


def test_pending_user_approval_rule_in_lifecycle_rules():
    """A LifecycleRule for pending_user_approval must exist.

    RED: No pending_user_approval rule in LIFECYCLE_RULES.
    """
    from superharness.engine.lifecycle_rules import LIFECYCLE_RULES
    states = {r.state for r in LIFECYCLE_RULES}
    assert "pending_user_approval" in states, (
        "LIFECYCLE_RULES must include a rule for 'pending_user_approval'."
    )


# ── Iter 10 RED: plan_approved timeout escalates a stale task ─────────────────

def test_plan_approved_timeout_escalates(tmp_path):
    """A plan_approved task older than its timeout must be auto-failed by reconcile_lifecycle.

    RED: No plan_approved rule exists → reconcile_lifecycle does nothing → status stays plan_approved.
    """
    project, conn = _setup_project(tmp_path)
    # Set plan_approved 300 minutes ago (well past any reasonable timeout)
    _insert_task(conn, "task-plan-approved", "plan_approved",
                 "plan_approved_at", _now_iso(-300))
    conn.close()

    from superharness.engine.lifecycle_rules import _scan_contract, LIFECYCLE_RULES
    from superharness.engine import state_reader

    # Verify the rule exists before running (if not, skip with a clear message)
    states = {r.state for r in LIFECYCLE_RULES}
    if "plan_approved" not in states:
        pytest.fail(
            "test_plan_approved_timeout_escalates: no plan_approved rule in LIFECYCLE_RULES — "
            "add LifecycleRule(state='plan_approved', ...) to LIFECYCLE_RULES"
        )

    profile: dict = {}
    changed = _scan_contract(str(project), LIFECYCLE_RULES, profile)
    assert changed >= 1, (
        f"Expected reconcile_lifecycle to escalate the stale plan_approved task; got changed={changed}"
    )

    tasks = state_reader.get_tasks(str(project))
    task = next((t for t in tasks if t.get("id") == "task-plan-approved"), None)
    assert task is not None, "task not found after reconcile"
    assert task.get("status") != "plan_approved", (
        f"Task must be escalated out of plan_approved; still has status={task.get('status')!r}"
    )


# ── Regression: existing rules untouched ─────────────────────────────────────

def test_existing_rules_still_present():
    """Adding new rules must not remove existing ones."""
    from superharness.engine.lifecycle_rules import LIFECYCLE_RULES
    expected = {"in_progress", "report_ready", "todo", "review_requested", "waiting_input"}
    states = {r.state for r in LIFECYCLE_RULES}
    missing = expected - states
    assert not missing, f"Existing lifecycle rules missing after edit: {missing}"
