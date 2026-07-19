"""Tests for engine.liveness — DB heartbeat timestamp + is_fresh(ttl) helper.

See docs/PLAN-steal-omnigent.md iteration 2.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from superharness.engine.db import get_connection, init_db
from superharness.engine.liveness import is_fresh, read_watcher_last_seen, touch_watcher


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_is_fresh_within_ttl():
    ts = _iso(datetime.now(timezone.utc) - timedelta(seconds=30))
    assert is_fresh(ts, ttl_seconds=90) is True


def test_is_fresh_expired():
    ts = _iso(datetime.now(timezone.utc) - timedelta(seconds=120))
    assert is_fresh(ts, ttl_seconds=90) is False


def test_is_fresh_none_or_malformed():
    assert is_fresh(None) is False
    assert is_fresh("garbage") is False


def test_touch_and_read_roundtrip(clean_harness):
    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        touch_watcher(conn, str(clean_harness))
        last_seen = read_watcher_last_seen(conn)
        assert last_seen is not None
        assert is_fresh(last_seen) is True
    finally:
        conn.close()


def test_status_renders_fresh_then_stale(clean_harness):
    """Integration: watcher cycle stamp -> status-level helper sees fresh;
    fake-age the row -> status-level helper sees stale.

    Regression guard for the "watcher stale 6023m — dead or deliberately
    down" ambiguity (2026-07-19 session): fresh and stale must render
    distinctly through the same is_fresh() decision point status.py uses.
    """
    conn = get_connection(str(clean_harness))
    try:
        init_db(conn)
        touch_watcher(conn, str(clean_harness))
        assert is_fresh(read_watcher_last_seen(conn)) is True

        stale_ts = _iso(datetime.now(timezone.utc) - timedelta(seconds=200))
        conn.execute(
            "UPDATE agent_heartbeats SET written_at = ? WHERE agent = 'watcher'",
            (stale_ts,),
        )
        conn.commit()
        assert is_fresh(read_watcher_last_seen(conn)) is False
    finally:
        conn.close()
