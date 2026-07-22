from __future__ import annotations

import sqlite3
import pytest

from superharness.engine import inbox_dao
from superharness.engine.state_errors import StateError

T0 = "2026-01-01T00:00:00Z"
T1 = "2026-01-01T01:00:00Z"
T2 = "2026-01-01T03:00:00Z"


def _make_task(db_conn, task_id="t1"):
    db_conn.execute(
        "INSERT INTO tasks (id, title, status, version, created_at) VALUES (?, 'T', 'todo', 1, ?)",
        (task_id, T0),
    )
    db_conn.commit()


def test_enqueue_and_get(db_conn):
    _make_task(db_conn)
    row = inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="claude-code", now=T0)
    assert row.id == "i1"
    assert row.status == "pending"
    assert row.created_at == T0
    assert not row.plan_only

    fetched = inbox_dao.get(db_conn, "i1")
    assert fetched == row


def test_enqueue_duplicate_raises(db_conn):
    _make_task(db_conn)
    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="claude-code", now=T0)
    with pytest.raises(StateError):
        inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="claude-code", now=T0)


def test_get_none(db_conn):
    assert inbox_dao.get(db_conn, "missing") is None


def test_get_all_filters(db_conn):
    _make_task(db_conn, "t1")
    _make_task(db_conn, "t2")
    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="a1", now=T0)
    inbox_dao.enqueue(db_conn, id="i2", task_id="t2", target_agent="a2", now=T0)

    all_rows = inbox_dao.get_all(db_conn)
    assert len(all_rows) == 2

    a1_rows = inbox_dao.get_all(db_conn, target_agent="a1")
    assert [r.id for r in a1_rows] == ["i1"]


def test_claim_next_atomic(db_conn):
    _make_task(db_conn)
    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="claude-code", now=T0)

    claimed = inbox_dao.claim_next(db_conn, target_agent="claude-code", pid=42, now=T1)
    assert claimed is not None
    assert claimed.id == "i1"
    assert claimed.status == "launched"
    assert claimed.pid == 42
    assert claimed.launched_at == T1

    # Second claim should find nothing
    second = inbox_dao.claim_next(db_conn, target_agent="claude-code", pid=99, now=T1)
    assert second is None


def test_claim_next_respects_priority(db_conn):
    _make_task(db_conn, "t1")
    _make_task(db_conn, "t2")
    inbox_dao.enqueue(db_conn, id="i-low", task_id="t1", target_agent="a", priority=1, now=T0)
    inbox_dao.enqueue(db_conn, id="i-high", task_id="t2", target_agent="a", priority=5, now=T0)

    claimed = inbox_dao.claim_next(db_conn, target_agent="a", pid=1, now=T1)
    assert claimed is not None
    assert claimed.id == "i-high"


def test_update_status_success(db_conn):
    _make_task(db_conn)
    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="a", now=T0)
    result = inbox_dao.update_status(db_conn, "i1", from_status="pending", to_status="launched", now=T1)
    assert result is True
    assert inbox_dao.get(db_conn, "i1").status == "launched"


def test_update_status_wrong_from(db_conn):
    _make_task(db_conn)
    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="a", now=T0)
    result = inbox_dao.update_status(db_conn, "i1", from_status="done", to_status="failed", now=T1)
    assert result is False


def test_mark_heartbeat(db_conn):
    _make_task(db_conn)
    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="a", now=T0)
    inbox_dao.mark_heartbeat(db_conn, "i1", T1)
    assert inbox_dao.get(db_conn, "i1").last_heartbeat == T1


def test_mark_heartbeat_missing_noop(db_conn):
    inbox_dao.mark_heartbeat(db_conn, "nonexistent", T0)  # should not raise


def test_get_stale(db_conn):
    _make_task(db_conn)
    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="a", now=T0)
    inbox_dao.update_status(db_conn, "i1", from_status="pending", to_status="launched", now=T0)
    db_conn.execute("UPDATE inbox SET last_heartbeat=? WHERE id='i1'", (T0,))
    db_conn.commit()

    stale = inbox_dao.get_stale(db_conn, timeout_seconds=60, now=T2)
    assert any(r.id == "i1" for r in stale)


def test_set_retry(db_conn):
    _make_task(db_conn)
    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="a", now=T0)
    inbox_dao.set_retry(db_conn, "i1", retry_count=1, failed_reason="timeout", now=T1)
    row = inbox_dao.get(db_conn, "i1")
    assert row.retry_count == 1
    assert row.failed_reason == "timeout"
    assert row.status == "pending"


def test_sync_task_status_transitions_active_items(db_conn):
    """Regression test for the sync_task_status silent-no-op bug: session-stop.sh
    and session-exit.sh hooks call `inbox sync_task_status --task <id> --to stopped`
    on every session end, but the CLI had no handler for it (function was deleted
    in c5d68ea3 while the docstring/help text/hooks kept referencing it) — the
    command always fell through to UsageError, swallowed by the hooks' `|| true`.
    """
    _make_task(db_conn, "t1")
    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="claude-code", now=T0)
    inbox_dao.update_status(db_conn, "i1", from_status="pending", to_status="launched", now=T0)

    synced = inbox_dao.sync_task_status(db_conn, task_id="t1", to_status="stopped", now=T1)

    assert synced == 1
    row = inbox_dao.get(db_conn, "i1")
    assert row.status == "stopped"
    assert row.pid is None


def test_sync_task_status_ignores_terminal_items(db_conn):
    """Only pending/launched/running/paused items sync — a done/failed item
    must not be resurrected into 'stopped' by a late-arriving session hook."""
    _make_task(db_conn, "t1")
    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="claude-code", now=T0)
    inbox_dao.update_status(db_conn, "i1", from_status="pending", to_status="done", now=T0)

    synced = inbox_dao.sync_task_status(db_conn, task_id="t1", to_status="stopped", now=T1)

    assert synced == 0
    assert inbox_dao.get(db_conn, "i1").status == "done"


def test_sync_task_status_no_matching_task(db_conn):
    assert inbox_dao.sync_task_status(db_conn, task_id="nonexistent", to_status="stopped", now=T1) == 0
