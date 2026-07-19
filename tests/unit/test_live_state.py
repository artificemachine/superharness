"""Tests for engine.live_state — ordered, deduped, retrying write chokepoint.

See docs/PLAN-steal-omnigent.md iteration 3.
"""
from __future__ import annotations

import logging
import threading

from superharness.engine.live_state import LiveStateWriter
from superharness.engine.db import get_connection, init_db


def test_writes_applied_in_submission_order(clean_harness):
    written: list[str] = []
    lock = threading.Lock()

    def write_fn(key: str, value: str) -> None:
        with lock:
            written.append(value)

    writer = LiveStateWriter(write_fn)
    writer.publish("k1", "running")
    writer.publish("k1", "idle")
    assert writer.flush(timeout=5) is True
    assert written == ["running", "idle"]


def test_duplicate_status_writes_once():
    calls: list[tuple[str, str]] = []

    def write_fn(key: str, value: str) -> None:
        calls.append((key, value))

    writer = LiveStateWriter(write_fn)
    writer.publish("k1", "same")
    writer.publish("k1", "same")
    assert writer.flush(timeout=5) is True
    assert calls == [("k1", "same")]


def test_failed_write_evicts_dedupe_and_retries():
    attempts: list[int] = []

    def write_fn(key: str, value: str) -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("simulated transient failure")

    writer = LiveStateWriter(write_fn)
    writer.publish("k1", "v")
    assert writer.flush(timeout=5) is True
    # first attempt failed; dedupe entry evicted so identical publish retries
    writer.publish("k1", "v")
    assert writer.flush(timeout=5) is True
    assert len(attempts) == 2


def test_flush_drains_queue():
    order: list[str] = []

    def write_fn(key: str, value: str) -> None:
        import time
        time.sleep(0.05)
        order.append(value)

    writer = LiveStateWriter(write_fn)
    writer.publish("k1", "a")
    assert writer.flush(timeout=5) is True
    assert order == ["a"]


def test_writer_exception_is_logged_not_raised(caplog, monkeypatch):
    # logging_utils.get_logger() sets logging.getLogger("superharness")
    # .propagate = False the first time ANY superharness.* logger is used
    # (process-wide, cached on the Logger singleton). If an earlier test in
    # the same pytest process triggered that, records from
    # superharness.engine.live_state stop reaching caplog's root-attached
    # handler even though they're still logged. Force propagation back on
    # for the duration of this assertion.
    monkeypatch.setattr(logging.getLogger("superharness"), "propagate", True)

    def write_fn(key: str, value: str) -> None:
        raise ValueError("boom")

    writer = LiveStateWriter(write_fn)
    with caplog.at_level(logging.WARNING):
        writer.publish("my-special-key", "v")
        assert writer.flush(timeout=5) is True
    assert any("my-special-key" in rec.message for rec in caplog.records)


def test_live_state_write_lands_in_real_sqlite(clean_harness):
    """Integration: publish through the chokepoint lands a row via get_connection.

    write_fn opens its own connection per call (as real call sites do) since
    sqlite3 connections are thread-affine and the chokepoint applies writes
    on its own worker thread.
    """
    project_dir = str(clean_harness)
    setup_conn = get_connection(project_dir)
    init_db(setup_conn)
    setup_conn.execute(
        "CREATE TABLE IF NOT EXISTS test_live_state_kv (key TEXT PRIMARY KEY, value TEXT)"
    )
    setup_conn.commit()
    setup_conn.close()

    def write_fn(key: str, value: str) -> None:
        conn = get_connection(project_dir)
        try:
            conn.execute(
                "INSERT INTO test_live_state_kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()

    writer = LiveStateWriter(write_fn)
    writer.publish("task1", "in_progress")
    assert writer.flush(timeout=5) is True

    verify_conn = get_connection(project_dir)
    row = verify_conn.execute(
        "SELECT value FROM test_live_state_kv WHERE key = 'task1'"
    ).fetchone()
    assert row is not None
    assert row["value"] == "in_progress"
    verify_conn.close()
