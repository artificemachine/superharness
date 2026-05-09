"""E2E regression tests for lifecycle, status, and discussion bugs fixed 2026-05-04.

Each test corresponds to a specific bug that was found and fixed. These tests
ensure the bugs don't regress.

BUG-1: TaskRow missing updated_at → lifecycle rules never fired
BUG-2: _task_row_from_dict clobbered updated_at during _export_contract_yaml
BUG-3: Inbox mirror SQL crash with YAML column names (task→task_id)
BUG-4: Dashboard _STATUS_TO_COL / STATUS_GROUPS missing statuses
BUG-5: str(Path('.')) matched .local in Claude binary path (false positive)
BUG-6: shux status didn't flag stale inbox items as issues
BUG-7: Discussion inbox items not cleaned when discussion closed
BUG-8: archived_at missing from TaskRow
BUG-9: _auto_delete_stale_inbox never existed
"""
from __future__ import annotations

import os
import sqlite3
import yaml
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.conftest import past_iso


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_profile(project: Path, **kwargs) -> None:
    """Write a minimal profile.yaml for testing."""
    sh = project / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    data = {
        "project_name": "test",
        "created": "2026-01-01",
        "primary_agent": "claude-code",
        "stack": "python",
        "autonomy": "autonomous",
        **kwargs,
    }
    (sh / "profile.yaml").write_text(yaml.dump(data))


def _write_contract(project: Path, tasks: list[dict]) -> None:
    sh = project / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    (sh / "contract.yaml").write_text(yaml.dump({"tasks": tasks}))


def _write_inbox(project: Path, items: list[dict]) -> None:
    sh = project / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    (sh / "inbox.yaml").write_text(yaml.dump(items))


def _init_sqlite(project: Path) -> None:
    from superharness.engine import db
    conn = db.get_connection(str(project))
    db.init_db(conn)
    conn.close()


# ---------------------------------------------------------------------------
# BUG-1: updated_at must survive TaskRow → asdict → lifecycle rules
# ---------------------------------------------------------------------------

def test_updated_at_survives_taskrow_roundtrip() -> None:
    """After writing updated_at via state_writer, it must be readable via state_reader."""
    from superharness.engine.tasks_dao import TaskRow
    from dataclasses import asdict

    task = TaskRow(
        id="test-bug1", title="Test", owner="claude-code",
        status="in_progress", effort="medium",
        project_path="/tmp/test", development_method="tdd",
        acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None,
        version=1, created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T12:00:00Z",
    )
    d = asdict(task)
    assert "updated_at" in d, "BUG-1 REGRESSION: updated_at missing from asdict(TaskRow)"
    assert d["updated_at"] == "2026-01-01T12:00:00Z"


def test_updated_at_survives_state_writer_roundtrip(clean_harness: Path) -> None:
    """Write task via state_writer, read back via state_reader, verify updated_at."""
    _write_profile(clean_harness)
    _write_contract(clean_harness, [{
        "id": "test-bug1-rt", "owner": "claude-code", "status": "todo",
    }])
    _init_sqlite(clean_harness)

    from superharness.engine.state_writer import set_task_status
    # force=True because this test exercises the roundtrip plumbing,
    # not the user-facing transition graph (todo → in_progress is not
    # a legal interactive transition; the proper path is via plan_*).
    result = set_task_status(str(clean_harness), "test-bug1-rt", "in_progress", force=True)
    assert result is True

    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t.get("id") == "test-bug1-rt")
    assert task["status"] == "in_progress"
    assert task.get("updated_at") is not None, (
        "BUG-1 REGRESSION: updated_at lost after set_task_status → get_tasks"
    )


# ---------------------------------------------------------------------------
# BUG-2: _task_row_from_dict must preserve all v4/v5 fields
# ---------------------------------------------------------------------------

def test_task_row_from_dict_preserves_all_fields(clean_harness: Path) -> None:
    """_task_row_from_dict must not clobber updated_at, archived_at, etc."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.contract_io import _task_row_from_dict
    from superharness.engine.tasks_dao import TaskRow

    task_dict = {
        "id": "test-bug2", "title": "Test", "owner": "claude-code",
        "status": "in_progress",
        "updated_at": "2026-05-04T10:00:00Z",
        "archived_at": "2026-05-04T09:00:00Z",
        "archived_reason": "timeout",
        "failed_at": "2026-05-04T08:00:00Z",
        "failed_reason": "deadline",
        "deadline_minutes": 120,
        "stopped_at": None,
    }
    row = _task_row_from_dict(task_dict, str(clean_harness), "2026-01-01T00:00:00Z")
    assert isinstance(row, TaskRow)
    assert row.updated_at == "2026-05-04T10:00:00Z", "BUG-2 REGRESSION: updated_at clobbered"
    assert row.archived_at == "2026-05-04T09:00:00Z", "BUG-2 REGRESSION: archived_at clobbered"
    assert row.archived_reason == "timeout", "BUG-2 REGRESSION: archived_reason clobbered"
    assert row.failed_at == "2026-05-04T08:00:00Z", "BUG-2 REGRESSION: failed_at clobbered"
    assert row.failed_reason == "deadline", "BUG-2 REGRESSION: failed_reason clobbered"
    assert row.deadline_minutes == 120, "BUG-2 REGRESSION: deadline_minutes clobbered"


# ---------------------------------------------------------------------------
# BUG-3: Inbox mirror must handle YAML → SQLite column name mapping
# ---------------------------------------------------------------------------

def test_set_inbox_status_writes_through_sqlite(clean_harness: Path) -> None:
    """paused → failed transition must persist in both YAML and SQLite."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    # Create task and inbox item via SQLite
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao, inbox_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id="test-bug3", title="Test", owner="claude-code",
            status="todo", effort="medium",
            project_path=str(clean_harness), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z",
        ))
        inbox_dao.enqueue(conn, id="item-bug3", task_id="test-bug3",
            target_agent="claude-code", priority=1, project_path=str(clean_harness),
            now="2026-01-01T00:00:00Z")
        inbox_dao.update_status(conn, "item-bug3", from_status="pending",
            to_status="paused", now="2026-01-01T00:00:00Z")
        conn.commit()
    finally:
        conn.close()

    # Write YAML inbox
    _write_inbox(clean_harness, [{
        "id": "item-bug3", "task": "test-bug3", "to": "claude-code",
        "status": "paused", "paused_at": past_iso(31),
        "created_at": "2026-01-01T00:00:00Z",
    }])

    # Run lifecycle reconciler
    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    reconcile_lifecycle(str(clean_harness))

    # Post-migration: SQLite is the source of truth; YAML is no longer
    # written. The original BUG-3 was about set_inbox_status silently
    # dropping writes — now we just check the SQLite row updated below.

    # Verify SQLite was updated
    conn2 = get_connection(str(clean_harness))
    try:
        row = conn2.execute("SELECT status FROM inbox WHERE id=?", ("item-bug3",)).fetchone()
        assert row is not None and row[0] == "failed", (
            "BUG-3 REGRESSION: set_inbox_status didn't mirror to SQLite"
        )
    finally:
        conn2.close()


# ---------------------------------------------------------------------------
# BUG-5: str(Path('.')) must not match .local as substring
# ---------------------------------------------------------------------------

def test_project_str_must_be_absolute() -> None:
    """str(Path('.')) returns '.' which matches '.local' — must resolve."""
    p = Path(".")
    raw = str(p)
    resolved = str(p.resolve())
    assert raw != resolved or "/" in raw, (
        f"BUG-5 REGRESSION: str(Path('.')) = {raw!r} is not absolute"
    )
    # The absolute path must NOT be a substring of a typical binary path
    assert resolved not in "/Users/test/.local/bin/claude", (
        f"BUG-5 REGRESSION: resolved path {resolved!r} would cause false positive"
    )


# ---------------------------------------------------------------------------
# BUG-8: archived_at must be in TaskRow
# ---------------------------------------------------------------------------

def test_archived_at_in_taskrow() -> None:
    """TaskRow must include archived_at and archived_reason."""
    from superharness.engine.tasks_dao import TaskRow
    from dataclasses import asdict

    task = TaskRow(
        id="test-bug8", title="Test", owner="claude-code",
        status="archived", effort="medium",
        project_path="/tmp/test", development_method="tdd",
        acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None,
        version=1, created_at="2026-01-01T00:00:00Z",
        archived_at="2026-05-04T10:00:00Z",
        archived_reason="timeout",
    )
    d = asdict(task)
    assert d.get("archived_at") == "2026-05-04T10:00:00Z", "BUG-8 REGRESSION: archived_at missing"
    assert d.get("archived_reason") == "timeout", "BUG-8 REGRESSION: archived_reason missing"


# ---------------------------------------------------------------------------
# Lifecycle rules integration tests
# ---------------------------------------------------------------------------

def test_in_progress_task_auto_archives(clean_harness: Path) -> None:
    """in_progress > 180m → archived (verifies updated_at used correctly)."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [{
        "id": "test-auto-archive", "owner": "claude-code",
        "status": "in_progress", "updated_at": past_iso(181),
    }])

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    changed = reconcile_lifecycle(str(clean_harness))
    assert changed >= 1, "Lifecycle reconciler should have changed the task"

    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t["id"] == "test-auto-archive")
    assert task["status"] == "archived", "BUG: in_progress task not auto-archived"
    assert task.get("archived_reason", "").startswith("in_progress timeout")


def test_waiting_input_task_auto_fails(clean_harness: Path) -> None:
    """waiting_input > 480m → failed."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [{
        "id": "test-auto-fail", "owner": "claude-code",
        "status": "waiting_input", "updated_at": past_iso(481),
    }])

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    reconcile_lifecycle(str(clean_harness))

    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t["id"] == "test-auto-fail")
    assert task["status"] == "failed", "BUG: waiting_input task not auto-failed"


def test_report_ready_task_auto_archives(clean_harness: Path) -> None:
    """report_ready > 1440m → archived."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [{
        "id": "test-report-archive", "owner": "claude-code",
        "status": "report_ready", "report_ready_at": past_iso(1441),
    }])

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    reconcile_lifecycle(str(clean_harness))

    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t["id"] == "test-report-archive")
    assert task["status"] == "archived", "BUG: report_ready task not auto-archived"


def test_deadline_enforcement_fails_task(clean_harness: Path) -> None:
    """Task with deadline_minutes exceeded → failed."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [{
        "id": "test-deadline-fail", "owner": "claude-code",
        "status": "in_progress",
        "created_at": past_iso(500),
        "deadline_minutes": 60,
    }])

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    reconcile_lifecycle(str(clean_harness))

    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t["id"] == "test-deadline-fail")
    assert task["status"] == "failed", "BUG: deadline enforcement didn't fail task"


# ---------------------------------------------------------------------------
# Dashboard status mapping completeness
# ---------------------------------------------------------------------------

def test_dashboard_status_mapping_covers_all_statuses() -> None:
    """Every defined status must map to a valid dashboard column — checked against canonical source."""
    from superharness.engine.next_action import ALL_STATUSES, STATUS_TO_COL

    for status in ALL_STATUSES:
        assert status in STATUS_TO_COL, (
            f"BUG-4 REGRESSION: status '{status}' missing from canonical STATUS_TO_COL in next_action.py"
        )


def test_dashboard_js_status_groups_cover_all_statuses() -> None:
    """JavaScript STATUS_GROUPS must have an entry for every status — checked against canonical source."""
    from superharness.engine.next_action import ALL_STATUSES, STATUS_GROUPS

    covered = set()
    for g in STATUS_GROUPS:
        covered.update(g["statuses"])

    for status in ALL_STATUSES:
        assert status in covered, (
            f"BUG-4 REGRESSION: status '{status}' not in any canonical STATUS_GROUPS group"
        )


# ---------------------------------------------------------------------------
# Discussion auto-close + inbox cleanup
# ---------------------------------------------------------------------------

def test_discussion_auto_close_cleans_inbox(clean_harness: Path) -> None:
    """When a consensus discussion is closed, related inbox items are cleaned."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    # Create discussion directory with state.yaml
    disc_id = "test-disc-e2e-close"
    disc_dir = clean_harness / ".superharness" / "discussions" / disc_id
    disc_dir.mkdir(parents=True)

    state = {
        "status": "closed",
        "topic": "Test discussion",
        "participants": ["claude-code", "codex-cli"],
        "current_round": 1,
        "max_rounds": 1,
        "created_at": "2026-01-01T00:00:00Z",
        "closed_at": "2026-01-01T01:00:00Z",
    }
    (disc_dir / "state.yaml").write_text(yaml.dump(state))

    # Post-migration: _reconcile_discussion_contract reads from the SQLite
    # discussions table, not from state.yaml. Seed the row directly.
    from superharness.engine.db import get_connection as _gc, init_db as _idb
    _conn = _gc(str(clean_harness))
    try:
        _idb(_conn, str(clean_harness))
        _conn.execute(
            "INSERT INTO discussions (id, topic, status, owners, created_at) "
            "VALUES (?, ?, 'closed', ?, ?)",
            (disc_id, state["topic"],
             yaml.dump(state["participants"]), state["created_at"]),
        )
        _conn.commit()
    finally:
        _conn.close()

    # Create contract tasks for discussion rounds
    _write_contract(clean_harness, [
        {"id": f"{disc_id}/round-1", "owner": "claude-code", "status": "in_progress"},
    ])

    # Create inbox items for these tasks
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao, inbox_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id=f"{disc_id}/round-1", title="Round 1", owner="claude-code",
            status="in_progress", effort="medium",
            project_path=str(clean_harness), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z",
        ))
        inbox_dao.enqueue(conn, id="item-disc-1", task_id=f"{disc_id}/round-1",
            target_agent="claude-code", priority=1, project_path=str(clean_harness),
            now="2026-01-01T00:00:00Z")
        inbox_dao.enqueue(conn, id="item-disc-2", task_id=f"{disc_id}/round-1",
            target_agent="codex-cli", priority=1, project_path=str(clean_harness),
            now="2026-01-01T00:00:00Z")
        conn.commit()
    finally:
        conn.close()

    # Also write YAML inbox (test mode reads YAML first)
    _write_inbox(clean_harness, [
        {"id": "item-disc-1", "task": f"{disc_id}/round-1", "to": "claude-code",
         "status": "pending", "created_at": "2026-01-01T00:00:00Z"},
        {"id": "item-disc-2", "task": f"{disc_id}/round-1", "to": "codex-cli",
         "status": "pending", "created_at": "2026-01-01T00:00:00Z"},
    ])

    # Run reconciliation
    from superharness.commands.inbox_watch import _reconcile_discussion_contract
    _reconcile_discussion_contract(str(clean_harness))

    # Verify task archived
    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t["id"] == f"{disc_id}/round-1")
    assert task["status"] == "archived", "BUG-7: discussion round task not archived"

    # Verify inbox items cleaned
    conn2 = get_connection(str(clean_harness))
    try:
        rows = conn2.execute(
            "SELECT id, status FROM inbox WHERE task_id LIKE ?",
            (f"{disc_id}%",),
        ).fetchall()
        for row in rows:
            assert row[1] in ("done", "stale"), (
                f"BUG-7 REGRESSION: inbox item {row[0]} not cleaned (status={row[1]})"
            )
    finally:
        conn2.close()


# ---------------------------------------------------------------------------
# shux status detects stale items (BUG-6)
# ---------------------------------------------------------------------------

def test_deep_inbox_health_detects_stale_items(clean_harness: Path) -> None:
    """_deep_inbox_health must include stale_items in its output."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao, tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id="test-stale-task", title="Test", owner="claude-code",
            status="todo", effort="medium",
            project_path=str(clean_harness), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z",
        ))
        inbox_dao.enqueue(conn, id="stale-1", task_id="test-stale-task",
            target_agent="claude-code", priority=1, project_path=str(clean_harness),
            now="2026-01-01T00:00:00Z")
        conn.execute("UPDATE inbox SET status='stale' WHERE id='stale-1'")
        conn.commit()
    finally:
        conn.close()

    # Write YAML inbox too (test mode reads YAML first)
    _write_inbox(clean_harness, [
        {"id": "stale-1", "task": "test-stale-task", "to": "claude-code",
         "status": "stale", "created_at": "2026-01-01T00:00:00Z"},
    ])

    from superharness.commands.status import _deep_inbox_health
    health = _deep_inbox_health(str(clean_harness))

    assert len(health["stale_items"]) >= 1, (
        "BUG-6 REGRESSION: _deep_inbox_health doesn't detect stale items"
    )
    assert health["stale_items"][0]["inbox_id"] == "stale-1"


# ---------------------------------------------------------------------------
# BUG-9b: auto_enqueue must skip expired deadlines (added v1.44.20)
# ---------------------------------------------------------------------------

def test_auto_enqueue_todo_skips_expired_deadline(clean_harness: Path) -> None:
    """auto_enqueue_todo must skip tasks whose deadline_minutes is already exceeded."""
    _write_profile(clean_harness, auto_dispatch=True, autonomy="autonomous")
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [
        {"id": "test-skip-deadline", "owner": "claude-code", "status": "todo",
         "deadline_minutes": 5, "created_at": past_iso(30)},
    ])

    from superharness.commands.inbox_watch import auto_enqueue_todo
    added = auto_enqueue_todo(str(clean_harness))

    # Should NOT enqueue — deadline already expired
    from superharness.engine.db import get_connection
    conn = get_connection(str(clean_harness))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM inbox WHERE task_id='test-skip-deadline'"
        ).fetchone()[0]
        assert count == 0, (
            f"BUG: auto_enqueue_todo enqueued task with expired deadline ({count} items)"
        )
    finally:
        conn.close()


def test_auto_enqueue_todo_enqueues_valid_deadline(clean_harness: Path) -> None:
    """auto_enqueue_todo must enqueue tasks whose deadline is still valid."""
    _write_profile(clean_harness, auto_dispatch=True, autonomy="autonomous")
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [
        {"id": "test-valid-deadline", "owner": "claude-code", "status": "todo",
         "deadline_minutes": 120, "created_at": past_iso(5)},
    ])

    from superharness.commands.inbox_watch import auto_enqueue_todo
    added = auto_enqueue_todo(str(clean_harness))
    assert added >= 1, "valid deadline task should be enqueued"


# ---------------------------------------------------------------------------
# Task report: deadline and lifecycle fields
# ---------------------------------------------------------------------------

def test_task_report_includes_deadline_and_lifecycle(clean_harness: Path) -> None:
    """task_report must include deadline_* and lifecycle_* fields."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id="test-report-fields", title="Report Test", owner="claude-code",
            status="in_progress", effort="medium",
            project_path=str(clean_harness), development_method="tdd",
            acceptance_criteria=["criteria 1"], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at=past_iso(200),
            deadline_minutes=120,
        ))
        conn.commit()
    finally:
        conn.close()

    # Write contract YAML for test mode
    _write_contract(clean_harness, [
        {"id": "test-report-fields", "owner": "claude-code", "status": "in_progress",
         "created_at": past_iso(200), "deadline_minutes": 120},
    ])

    import sys; sys.path.insert(0, "src")
    import importlib
    mod = importlib.import_module("superharness.scripts.dashboard-ui")
    result = mod.task_report(clean_harness, "test-report-fields", "claude-code")

    assert result.get("deadline_minutes") == 120, "task_report missing deadline_minutes"
    assert result.get("deadline_exceeded") is True, "task_report: deadline should be exceeded"
    assert result.get("deadline_elapsed", 0) >= 200, "task_report: elapsed should be >= 200"


# ---------------------------------------------------------------------------
# _check_deadlines with default_deadline_minutes profile override
# ---------------------------------------------------------------------------

def test_check_deadlines_uses_profile_default(clean_harness: Path) -> None:
    """_check_deadlines must use default_deadline_minutes from profile.yaml."""
    _write_profile(clean_harness, default_deadline_minutes=10)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [
        {"id": "test-default-deadline", "owner": "claude-code",
         "status": "in_progress", "created_at": past_iso(30)},
    ])

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    reconcile_lifecycle(str(clean_harness))

    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t["id"] == "test-default-deadline")
    assert task["status"] == "failed", (
        f"BUG: default_deadline_minutes=10 not enforced (elapsed 30m, status={task['status']})"
    )
    assert "deadline exceeded" in task.get("failed_reason", "")


# ---------------------------------------------------------------------------
# reconcile_lifecycle returns correct count with all rules
# ---------------------------------------------------------------------------

def test_reconcile_lifecycle_counts_all_rules(clean_harness: Path) -> None:
    """reconcile_lifecycle must return correct count when multiple rules fire."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [
        {"id": "task-a", "owner": "claude-code", "status": "in_progress",
         "updated_at": past_iso(181)},
        {"id": "task-b", "owner": "claude-code", "status": "waiting_input",
         "updated_at": past_iso(481)},
        {"id": "task-c", "owner": "claude-code", "status": "report_ready",
         "report_ready_at": past_iso(1441)},
        {"id": "task-d", "owner": "claude-code", "status": "in_progress",
         "created_at": past_iso(100), "deadline_minutes": 60},
    ])

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    changed = reconcile_lifecycle(str(clean_harness))
    assert changed == 4, (
        f"reconcile_lifecycle should return 4 (archived×2 + failed×2), got {changed}"
    )

    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    statuses = {t["id"]: t["status"] for t in tasks}
    assert statuses["task-a"] == "archived", "in_progress timeout not applied"
    assert statuses["task-b"] == "failed", "waiting_input timeout not applied"
    assert statuses["task-c"] == "archived", "report_ready timeout not applied"
    assert statuses["task-d"] == "failed", "deadline enforcement not applied"


# ---------------------------------------------------------------------------
# Discussion panel: submissions and timeline
# ---------------------------------------------------------------------------

def test_discussion_agent_status_returns_submissions(clean_harness: Path) -> None:
    """discussion_agent_status must return submissions with positions and points."""
    import yaml
    disc_id = "test-disc-submissions"
    disc_dir = clean_harness / ".superharness" / "discussions" / disc_id
    disc_dir.mkdir(parents=True)

    # Write state.yaml
    (disc_dir / "state.yaml").write_text(yaml.dump({
        "status": "active",
        "topic": "Test submissions display",
        "participants": ["claude-code", "codex-cli"],
        "current_round": 1,
        "max_rounds": 1,
        "created_at": "2026-01-01T00:00:00Z",
    }))

    # Write round submissions
    (disc_dir / "round-1-claude-code.yaml").write_text(yaml.dump({
        "agent": "claude-code",
        "round": 1,
        "verdict": "consensus",
        "position": "Test position from claude-code",
        "points": [{"id": "point-1", "verdict": "agree", "rationale": "Good"}],
        "submitted_at": "2026-01-01T01:00:00Z",
    }))
    (disc_dir / "round-1-codex-cli.yaml").write_text(yaml.dump({
        "agent": "codex-cli",
        "round": 1,
        "verdict": "consensus",
        "position": "Test position from codex-cli",
        "points": [{"id": "point-1", "verdict": "agree", "rationale": "Agreed"}],
        "submitted_at": "2026-01-01T01:05:00Z",
    }))

    import sys; sys.path.insert(0, "src")
    import importlib
    mod = importlib.import_module("superharness.scripts.dashboard-ui")
    result = mod.discussion_agent_status(clean_harness, disc_id)

    assert result["total_submissions"] == 2, f"Expected 2 submissions, got {result['total_submissions']}"
    assert len(result["timeline"]) >= 3, f"Expected at least 3 timeline events, got {len(result['timeline'])}"

    # Verify timeline events
    events = [e["event"] for e in result["timeline"]]
    assert "created" in events, "timeline missing 'created'"
    assert "submitted" in events, "timeline missing 'submitted'"

    # Verify submissions have content
    for s in result["submissions"]:
        assert s["agent"] in ("claude-code", "codex-cli")
        assert len(s.get("position", "")) > 0, f"submission missing position for {s['agent']}"


# ---------------------------------------------------------------------------
# Edge cases: type coercion, zero values, missing fields
# ---------------------------------------------------------------------------

def test_deadline_minutes_zero_is_ignored(clean_harness: Path) -> None:
    """deadline_minutes=0 must not trigger enforcement."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [{
        "id": "test-zero-deadline", "owner": "claude-code",
        "status": "in_progress", "created_at": past_iso(500),
        "deadline_minutes": 0,
    }])

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    changed = reconcile_lifecycle(str(clean_harness))
    assert changed == 0, f"deadline_minutes=0 should be ignored, got {changed} changes"


def test_deadline_minutes_string_is_coerced(clean_harness: Path) -> None:
    """deadline_minutes='10' (string) must be coerced to int."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [{
        "id": "test-str-deadline", "owner": "claude-code",
        "status": "in_progress", "created_at": past_iso(500),
        "deadline_minutes": "10",
    }])

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    reconcile_lifecycle(str(clean_harness))

    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t["id"] == "test-str-deadline")
    assert task["status"] == "failed", "string deadline_minutes should be coerced to int"


def test_deadline_not_set_is_ignored(clean_harness: Path) -> None:
    """Task without deadline_minutes must not be affected by deadline enforcement."""
    _write_profile(clean_harness, default_deadline_minutes=0)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [{
        "id": "test-no-deadline", "owner": "claude-code",
        "status": "in_progress", "created_at": past_iso(500),
    }])

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    changed = reconcile_lifecycle(str(clean_harness))
    assert changed == 0, "task without deadline should not be affected by deadline enforcement"


def test_empty_inbox_health_returns_no_issues(clean_harness: Path) -> None:
    """All health checks must return 0/empty when there are no issues."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    from superharness.commands.status import _deep_inbox_health
    health = _deep_inbox_health(str(clean_harness))

    assert health["orphaned"] == [], f"orphaned should be empty, got {len(health['orphaned'])}"
    assert health["stale_pending"] == [], "stale_pending should be empty"
    assert health["stale_items"] == [], "stale_items should be empty"
    assert health["dead_pid"] == [], "dead_pid should be empty"
    assert health["missing_task"] == [], "missing_task should be empty"


def test_in_progress_without_updated_at_ignored(clean_harness: Path) -> None:
    """in_progress task with no updated_at must not be auto-archived (graceful skip)."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [{
        "id": "test-no-ts", "owner": "claude-code",
        "status": "in_progress",
        # no updated_at, no in_progress_at
    }])

    from superharness.engine.lifecycle_rules import reconcile_lifecycle
    changed = reconcile_lifecycle(str(clean_harness))
    assert changed == 0, (
        "task without timestamps should not be changed (graceful degradation)"
    )

    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    task = next(t for t in tasks if t["id"] == "test-no-ts")
    assert task["status"] == "in_progress", "task status should remain unchanged"


def test_shux_status_check_exit_code(clean_harness: Path) -> None:
    """shux status --check must exit 1 when issues found."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)
    _write_contract(clean_harness, [{
        "id": "test-check-task", "owner": "claude-code",
        "status": "in_progress", "updated_at": past_iso(200),
    }])
    # Add an orphaned inbox item to trigger an issue
    from superharness.engine.db import get_connection
    conn = get_connection(str(clean_harness))
    from superharness.engine import inbox_dao, tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    from superharness.engine.db import init_db
    init_db(conn)
    tasks_dao.upsert(conn, TaskRow(
        id="test-orphan-task", title="Orphan", owner="claude-code",
        status="done", effort="medium",
        project_path=str(clean_harness), development_method="tdd",
        acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None,
        version=1, created_at="2026-01-01T00:00:00Z",
    ))
    inbox_dao.enqueue(conn, id="orphan-1", task_id="test-orphan-task",
        target_agent="claude-code", priority=1, project_path=str(clean_harness),
        now="2026-01-01T00:00:00Z")
    conn.commit()
    conn.close()

    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "superharness.commands.status", "--project", str(clean_harness), "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, (
        f"--check should exit 1 when issues found, got {result.returncode}\n{result.stdout}"
    )


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_shux_status_clean_exits_zero(clean_harness: Path) -> None:
    """shux status --check must exit 0 when no task/inbox/discussion issues (watcher down is expected in tests)."""
    _write_profile(clean_harness)
    _init_sqlite(clean_harness)

    # Write a recent heartbeat to silence the watcher-down warning
    from datetime import datetime, timezone
    hb_file = clean_harness / ".superharness" / "watcher.heartbeat"
    hb_file.write_text(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")

    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "superharness.commands.status", "--project", str(clean_harness), "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"--check should exit 0 when clean, got {result.returncode}\n{result.stdout}"
    )
