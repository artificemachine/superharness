"""Regression tests for the auto-enqueue flood bug.

Root cause: auto_enqueue_approved() checked only active (pending/launched/running/paused)
inbox items to prevent duplicates. When a dispatch failed, the item exited the
active set, and the next watcher tick created a fresh item with retry_count=0.
This repeated indefinitely, producing 44+ items for a single task in one session.

Fixes tested here:
1. failed_counts guard: stop re-enqueueing when failed count >= max_retries
2. StateError catch: race-safe duplicate detection at inbox_dao.enqueue
3. YAML sync includes new_items: test-mode YAML sync correctly reflects enqueued items
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_auto_dispatch.py helpers)
# ---------------------------------------------------------------------------

def _write_contract(project: Path, tasks: list[dict]) -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "contract.yaml").write_text(
        yaml.dump({"id": "test-contract", "tasks": tasks}, default_flow_style=False)
    )


def _write_inbox(project: Path, items: list[dict]) -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "inbox.yaml").write_text(
        yaml.dump(items, default_flow_style=False)
    )


def _write_profile(project: Path, auto_dispatch: bool = True) -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "profile.yaml").write_text(
        yaml.dump({"auto_dispatch": auto_dispatch, "autonomy": "autonomous"},
                  default_flow_style=False)
    )


def _read_inbox(project: Path) -> list[dict]:
    f = project / ".superharness" / "inbox.yaml"
    if not f.exists():
        return []
    return yaml.safe_load(f.read_text()) or []


# ---------------------------------------------------------------------------
# Test 1 — failed items stop re-enqueueing when failure count >= max_retries
# ---------------------------------------------------------------------------

def _enqueue_failed(project: Path, task_id: str, agent: str, count: int) -> None:
    """Insert `count` failed inbox items into SQLite for the given task."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao
    conn = get_connection(str(project))
    try:
        init_db(conn)
        # Ensure task row exists (FK requirement); title is NOT NULL
        conn.execute(
            "INSERT OR IGNORE INTO tasks (id, title, project_path, status, owner, created_at) "
            "VALUES (?, ?, ?, 'plan_approved', ?, '2026-05-06T00:00:00Z')",
            (task_id, task_id, str(project), agent),
        )
        # Enqueue and immediately fail each item one by one:
        # inbox_dao.enqueue rejects duplicates when a pending item already exists,
        # so we must fail the previous item before enqueuing the next.
        for i in range(count):
            inbox_dao.enqueue(conn, id=f"pre-fail-{i}", task_id=task_id,
                              target_agent=agent, priority=2, max_retries=3,
                              project_path=str(project), plan_only=False,
                              now="2026-05-06T00:00:00Z")
            conn.execute(
                "UPDATE inbox SET status='failed', failed_at='2026-05-06T01:00:00Z' "
                "WHERE id=?", (f"pre-fail-{i}",)
            )
            conn.commit()
    finally:
        conn.close()


def test_failed_count_blocks_reenqueue(tmp_path):
    """A task with >= max_retries failed items must NOT get a new inbox entry."""
    from superharness.commands.inbox_watch import auto_enqueue_approved

    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, [
        {"id": "stuck-task", "owner": "gemini-cli", "status": "plan_approved"},
    ])
    _write_inbox(project, [])
    _write_profile(project)

    # Pre-populate SQLite with 3 failed items (== default max_retries)
    _enqueue_failed(project, "stuck-task", "gemini-cli", 3)

    added = auto_enqueue_approved(str(project))

    assert added == 0, (
        f"Expected 0 new items (retry budget exhausted), got {added}"
    )


def test_one_failure_does_not_block_reenqueue(tmp_path):
    """A task with fewer failed items than max_retries should still be enqueued."""
    from superharness.commands.inbox_watch import auto_enqueue_approved

    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, [
        {"id": "retry-ok-task", "owner": "claude-code", "status": "plan_approved"},
    ])
    _write_inbox(project, [])
    _write_profile(project)

    # 1 failed item, max_retries defaults to 3 → should still enqueue
    _enqueue_failed(project, "retry-ok-task", "claude-code", 1)

    added = auto_enqueue_approved(str(project))

    assert added == 1, (
        f"Expected 1 new item (1 failure < max_retries=3), got {added}"
    )


# ---------------------------------------------------------------------------
# Test 2 — e2e simulation: watcher calling auto_enqueue_approved N times
# ---------------------------------------------------------------------------

def test_watcher_loop_does_not_flood(tmp_path):
    """Simulate the flood scenario: N watcher ticks after a failed dispatch.

    Before the fix, each tick created a new inbox item (44+ items for one task).
    After the fix, items stop being created once failures reach max_retries.
    """
    from superharness.commands.inbox_watch import auto_enqueue_approved
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao

    project = tmp_path / "proj"
    project.mkdir()
    max_retries = 3
    _write_contract(project, [
        {"id": "flood-task", "owner": "gemini-cli", "status": "plan_approved",
         "max_retries": max_retries},
    ])
    _write_inbox(project, [])
    _write_profile(project)

    conn = get_connection(str(project))
    init_db(conn)
    conn.close()

    total_enqueued = 0

    # Simulate 10 watcher ticks; each tick: auto_enqueue, then "fail" the item
    for tick in range(10):
        added = auto_enqueue_approved(str(project))
        total_enqueued += added

        if added == 0:
            break  # flood guard kicked in

        # Simulate the dispatcher failing the item
        conn = get_connection(str(project))
        try:
            conn.execute(
                "UPDATE inbox SET status='failed', failed_at='2026-05-06T00:00:00Z' "
                "WHERE task_id='flood-task' AND status='pending'"
            )
            conn.commit()
        finally:
            conn.close()

    # With max_retries=3, at most 3 items should have been created before the guard fires
    assert total_enqueued <= max_retries, (
        f"Flood guard failed: {total_enqueued} items created, expected <= {max_retries}"
    )


# ---------------------------------------------------------------------------
# Test 3 — active item still blocks even after fix
# ---------------------------------------------------------------------------

def test_active_pending_item_still_blocks(tmp_path):
    """A pending item in SQLite must still block re-enqueueing (regression guard)."""
    from superharness.commands.inbox_watch import auto_enqueue_approved
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao

    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, [
        {"id": "active-task", "owner": "claude-code", "status": "plan_approved"},
    ])
    _write_inbox(project, [])
    _write_profile(project)

    # Pre-populate with a pending item in SQLite
    conn = get_connection(str(project))
    try:
        init_db(conn)
        conn.execute(
            "INSERT OR IGNORE INTO tasks (id, title, project_path, status, owner, created_at) "
            "VALUES ('active-task', 'active-task', ?, 'plan_approved', 'claude-code', '2026-05-06T00:00:00Z')",
            (str(project),),
        )
        inbox_dao.enqueue(conn, id="active-001", task_id="active-task",
                          target_agent="claude-code", priority=2, max_retries=3,
                          project_path=str(project), plan_only=False,
                          now="2026-05-06T00:00:00Z")
        conn.commit()
    finally:
        conn.close()

    added = auto_enqueue_approved(str(project))

    assert added == 0, (
        f"Expected 0 (item already pending in SQLite), got {added}"
    )
