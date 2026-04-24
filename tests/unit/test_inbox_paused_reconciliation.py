"""Regression tests for paused-pid reconciliation in the watcher (Iteration 6).

A paused inbox item with a dead pid must be transitioned to failed on the
next watcher reconciliation pass. Paused items with a live pid or no pid
must be left untouched.
"""
from __future__ import annotations

import os

import pytest


def _make_inbox_item(status: str, pid: int | str | None = None) -> dict:
    item: dict = {
        "id": "item-001",
        "task_id": "feat.test-task",
        "to": "claude-code",
        "status": status,
        "enqueued_at": "2026-04-24T10:00:00Z",
        "priority": "normal",
    }
    if pid is not None:
        item["pid"] = str(pid)
    return item


def test_paused_item_with_dead_pid_transitions_to_failed():
    from superharness.commands.inbox_watch import _reconcile_paused_dead_pids

    dead_pid = 99999  # guaranteed not running on any reasonable system
    item = _make_inbox_item("paused", pid=dead_pid)
    inbox = [item]

    changed = _reconcile_paused_dead_pids(inbox)

    assert changed, "should report that a change was made"
    assert item["status"] == "failed"
    assert "pid" in item.get("failed_reason", "").lower() or str(dead_pid) in item.get("failed_reason", "")


def test_paused_item_with_live_pid_stays_paused():
    from superharness.commands.inbox_watch import _reconcile_paused_dead_pids

    live_pid = os.getpid()  # current process — guaranteed alive
    item = _make_inbox_item("paused", pid=live_pid)
    inbox = [item]

    changed = _reconcile_paused_dead_pids(inbox)

    assert not changed, "no change expected when pid is alive"
    assert item["status"] == "paused"


def test_paused_item_with_no_pid_stays_paused():
    from superharness.commands.inbox_watch import _reconcile_paused_dead_pids

    item = _make_inbox_item("paused")  # no pid field
    inbox = [item]

    changed = _reconcile_paused_dead_pids(inbox)

    assert not changed, "ambiguous — no pid means no liveness check"
    assert item["status"] == "paused"


def test_non_paused_item_is_not_touched():
    from superharness.commands.inbox_watch import _reconcile_paused_dead_pids

    dead_pid = 99999
    item = _make_inbox_item("running", pid=dead_pid)
    inbox = [item]

    changed = _reconcile_paused_dead_pids(inbox)

    assert not changed, "only paused items are reconciled by this function"
    assert item["status"] == "running"


def test_reconcile_is_idempotent():
    from superharness.commands.inbox_watch import _reconcile_paused_dead_pids

    dead_pid = 99999
    item = _make_inbox_item("paused", pid=dead_pid)
    inbox = [item]

    _reconcile_paused_dead_pids(inbox)
    assert item["status"] == "failed"

    changed_second = _reconcile_paused_dead_pids(inbox)
    assert not changed_second, "second pass on already-failed item must report no change"
    assert item["status"] == "failed"
