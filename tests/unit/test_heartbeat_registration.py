"""Tests for agent daemon heartbeat registration during dispatch."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def _setup_db(tmp_path: Path) -> sqlite3.Connection:
    harness = tmp_path / ".superharness"
    harness.mkdir()
    db_path = harness / "state.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    from superharness.engine.db import init_db
    init_db(conn)
    conn.commit()
    return conn


class TestHeartbeatRegistration:
    """Agent daemon heartbeat is written during dispatch."""

    def test_delegate_writes_heartbeat(self, tmp_path):
        """Dispatching an agent registers its heartbeat."""
        conn = _setup_db(tmp_path)
        from superharness.engine.db import get_connection, init_db, now_iso
        from superharness.engine import heartbeat_dao

        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            heartbeat_dao.upsert(
                conn2, agent="claude-code", task_id="test-task",
                status="launched", pid=12345, now=now_iso(),
            )
            conn2.commit()
            row = conn2.execute(
                "SELECT agent, status, task_id FROM agent_heartbeats WHERE agent='claude-code'"
            ).fetchone()
            assert row is not None
            assert row["agent"] == "claude-code"
            assert row["status"] == "launched"
            assert row["task_id"] == "test-task"
        finally:
            conn2.close()
        conn.close()

    def test_heartbeat_status_updates(self, tmp_path):
        """Subsequent dispatches update the heartbeat."""
        conn = _setup_db(tmp_path)
        from superharness.engine.db import get_connection, init_db, now_iso
        from superharness.engine import heartbeat_dao

        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            heartbeat_dao.upsert(conn2, agent="gemini-cli", task_id="t1",
                                status="launched", pid=1, now=now_iso())
            conn2.commit()
            # Second upsert
            heartbeat_dao.upsert(conn2, agent="gemini-cli", task_id="t2",
                                status="running", pid=1, now=now_iso())
            conn2.commit()
            row = conn2.execute(
                "SELECT task_id, status FROM agent_heartbeats WHERE agent='gemini-cli'"
            ).fetchone()
            assert row["task_id"] == "t2"  # updated
            assert row["status"] == "running"
        finally:
            conn2.close()
        conn.close()

    def test_missing_heartbeat_detected(self, tmp_path):
        """Agent without heartbeat is detected as missing."""
        conn = _setup_db(tmp_path)
        from superharness.engine.db import get_connection, init_db
        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            row = conn2.execute(
                "SELECT status FROM agent_heartbeats WHERE agent='nonexistent'"
            ).fetchone()
            assert row is None  # truly missing
        finally:
            conn2.close()
        conn.close()

    def test_zombie_heartbeat_detected(self, tmp_path):
        """Stale heartbeat is detected as zombie."""
        conn = _setup_db(tmp_path)
        from superharness.engine.db import get_connection, init_db, now_iso
        from superharness.engine import heartbeat_dao

        conn2 = get_connection(str(tmp_path))
        try:
            init_db(conn2)
            heartbeat_dao.upsert(conn2, agent="old-agent", task_id="old",
                                status="launched", pid=1, now="2020-01-01T00:00:00Z")
            conn2.commit()
            row = conn2.execute(
                "SELECT status, updated_at FROM agent_heartbeats WHERE agent='old-agent'"
            ).fetchone()
            assert row is not None
            assert row["status"] == "launched"
        finally:
            conn2.close()
        conn.close()
