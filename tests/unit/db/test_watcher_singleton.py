from __future__ import annotations

import sqlite3
import pytest
from superharness.engine.state_errors import SingletonConflict

def test_watcher_singleton_acquire_release(db_conn):
    from superharness.engine import watcher_singleton
    
    # First acquire
    lease = watcher_singleton.acquire(
        db_conn, pid=100, hostname="host1", now="2026-01-01T00:00:00Z"
    )
    assert lease.pid == 100
    
    # Second acquire fails
    with pytest.raises(SingletonConflict):
        watcher_singleton.acquire(
            db_conn, pid=101, hostname="host1", now="2026-01-01T00:00:01Z"
        )
    
    # Release
    watcher_singleton.release(db_conn, pid=100)
    
    # Acquire again succeeds
    lease2 = watcher_singleton.acquire(
        db_conn, pid=102, hostname="host1", now="2026-01-01T00:00:05Z"
    )
    assert lease2.pid == 102

def test_watcher_singleton_stale_takeover(db_conn):
    from superharness.engine import watcher_singleton
    
    # Initial acquire
    watcher_singleton.acquire(
        db_conn, pid=100, hostname="host1", now="2026-01-01T00:00:00Z"
    )
    
    # Takeover after stale threshold
    # SQLite datetime('2026-01-01T00:00:00Z') < datetime('2026-01-01T00:00:02Z', '-1 seconds')
    # is T00:00:00 < T00:00:01 which is TRUE.
    lease = watcher_singleton.acquire(
        db_conn, pid=101, hostname="host1", now="2026-01-01T00:00:02Z",
        stale_after_seconds=1
    )
    assert lease.pid == 101

def test_watcher_singleton_heartbeat(db_conn):
    from superharness.engine import watcher_singleton
    
    watcher_singleton.acquire(
        db_conn, pid=100, hostname="host1", now="2026-01-01T00:00:00Z"
    )
    
    # Successful heartbeat
    assert watcher_singleton.heartbeat(db_conn, pid=100, now="2026-01-01T00:00:30Z") is True
    
    # Heartbeat from wrong PID
    assert watcher_singleton.heartbeat(db_conn, pid=101, now="2026-01-01T00:00:31Z") is False
