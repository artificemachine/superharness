"""Watcher liveness: DB heartbeat timestamp + pure is_fresh(ttl) helper.

Replaces heuristic heartbeat-age parsing scattered across status.py with one
decision point: `is_fresh(last_seen)`. Reuses the existing `agent_heartbeats`
table (agent_id="watcher") via `watcher_heartbeat_dao` — the same table
`heartbeat_contract.read_heartbeat_db` / status.py already read, so touching
liveness here and rendering it in status.py observe the same signal instead
of introducing a second, parallel source of truth.

See docs/PLAN-steal-omnigent.md iteration 2.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

WATCHER_TTL_SECONDS = 90

_WATCHER_AGENT_ID = "watcher"


def is_fresh(ts_str: str | None, ttl_seconds: int = WATCHER_TTL_SECONDS) -> bool:
    """Pure: True if ts_str parses as ISO-8601 and is within ttl_seconds of now.

    Never raises — None, empty, or malformed timestamps return False.
    """
    if not ts_str or not isinstance(ts_str, str):
        return False
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return age < ttl_seconds


def touch_watcher(conn: sqlite3.Connection, project_dir: str) -> str:
    """Stamp watcher liveness at cycle start. Returns the timestamp written.

    project_dir is accepted for call-site symmetry with other per-project
    liveness helpers; the write itself is DB-connection scoped.
    """
    from superharness.engine import watcher_heartbeat_dao

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    watcher_heartbeat_dao.upsert(conn, agent_id=_WATCHER_AGENT_ID, written_at=now)
    conn.commit()
    return now


def read_watcher_last_seen(conn: sqlite3.Connection) -> str | None:
    """Return the watcher's last-seen timestamp, or None if never stamped."""
    from superharness.engine import watcher_heartbeat_dao

    row = watcher_heartbeat_dao.get(conn, _WATCHER_AGENT_ID)
    return row.written_at if row else None
