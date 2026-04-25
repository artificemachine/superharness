from __future__ import annotations

import sqlite3
import os
import socket
from dataclasses import dataclass
from typing import Any

from superharness.engine.state_errors import StateError, SingletonConflict

@dataclass(frozen=True)
class SingletonLease:
    pid: int
    hostname: str
    started_at: str
    last_heartbeat: str

_DEFAULT_HOSTNAME = socket.gethostname()

def acquire(
    conn: sqlite3.Connection,
    *,
    pid: int,
    hostname: str = _DEFAULT_HOSTNAME,
    now: str,
    stale_after_seconds: int = 120,
) -> SingletonLease:
    """Acquire the watcher singleton lease.
    
    1. No existing row: INSERT succeeds.
    2. Existing row with stale heartbeat: UPDATE with new PID succeeds.
    3. Otherwise: raises SingletonConflict.
    """
    try:
        # Try INSERT first
        conn.execute(
            """
            INSERT INTO watcher_instance (key, pid, hostname, started_at, last_heartbeat)
            VALUES ('singleton', ?, ?, ?, ?)
            """,
            (pid, hostname, now, now)
        )
        row = conn.execute("SELECT * FROM watcher_instance WHERE key='singleton'").fetchone()
        return _row_to_lease(row)
    except sqlite3.IntegrityError:
        pass # Row already exists, check if it's stale
    except sqlite3.Error as e:
        raise StateError(f"Failed to acquire watcher singleton: {e}") from e
        
    # Row exists: check staleness.
    # SQLite datetime() can't parse 'Z' suffix — compute cutoff in Python.
    from datetime import datetime, timezone, timedelta
    cutoff_dt = datetime.strptime(
        now.rstrip("Z"), "%Y-%m-%dT%H:%M:%S"
    ).replace(tzinfo=timezone.utc) - timedelta(seconds=stale_after_seconds)
    cutoff = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        cursor = conn.execute(
            """
            UPDATE watcher_instance
            SET pid = ?, hostname = ?, started_at = ?, last_heartbeat = ?
            WHERE key = 'singleton'
              AND last_heartbeat < ?
            """,
            (pid, hostname, now, now, cutoff),
        )
        if cursor.rowcount > 0:
            row = conn.execute("SELECT * FROM watcher_instance WHERE key='singleton'").fetchone()
            return _row_to_lease(row)
            
        # Not stale: someone else holds an active lease
        existing = conn.execute("SELECT * FROM watcher_instance WHERE key='singleton'").fetchone()
        holder_pid = existing["pid"] if existing else "unknown"
        raise SingletonConflict(f"Watcher singleton held by PID {holder_pid}; cannot acquire.")
    except SingletonConflict:
        raise
    except sqlite3.Error as e:
        raise StateError(f"Database error during singleton acquisition: {e}") from e

def heartbeat(conn: sqlite3.Connection, pid: int, now: str) -> bool:
    """Update last_heartbeat if the caller's PID owns the lease."""
    cursor = conn.execute(
        "UPDATE watcher_instance SET last_heartbeat = ? WHERE key = 'singleton' AND pid = ?",
        (now, pid)
    )
    return cursor.rowcount > 0

def release(conn: sqlite3.Connection, pid: int) -> None:
    """Delete the lease row if owned by this PID."""
    conn.execute("DELETE FROM watcher_instance WHERE key = 'singleton' AND pid = ?", (pid,))

def _row_to_lease(row: sqlite3.Row) -> SingletonLease:
    return SingletonLease(
        pid=row["pid"],
        hostname=row["hostname"],
        started_at=row["started_at"],
        last_heartbeat=row["last_heartbeat"]
    )
