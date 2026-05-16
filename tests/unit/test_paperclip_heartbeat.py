"""Tests for agent_heartbeats table (paperclip.heartbeat feature)."""
from __future__ import annotations

import pytest
from superharness.engine.db import get_connection, init_db
from superharness.engine import heartbeat_dao


@pytest.fixture
def conn(tmp_path):
    c = get_connection(str(tmp_path))
    init_db(c)
    yield c
    c.close()


NOW = "2026-05-16T10:00:00Z"
LATER = "2026-05-16T10:03:00Z"  # 3 min later — past 2-min stale threshold


def test_upsert_creates_row(conn):
    row = heartbeat_dao.upsert(conn, agent="claude-code", status="alive", now=NOW)
    assert row.agent == "claude-code"
    assert row.status == "alive"
    assert row.task_id is None


def test_upsert_updates_existing_row(conn):
    heartbeat_dao.upsert(conn, agent="claude-code", task_id="t-1", status="alive", now=NOW)
    conn.commit()
    row = heartbeat_dao.upsert(conn, agent="claude-code", task_id="t-2", status="paused", now=LATER)
    conn.commit()
    assert row.task_id == "t-2"
    assert row.status == "paused"
    # Only one row should exist per agent
    all_rows = heartbeat_dao.get_all(conn)
    assert sum(1 for r in all_rows if r.agent == "claude-code") == 1


def test_get_returns_agent_row(conn):
    heartbeat_dao.upsert(conn, agent="codex-cli", status="alive", now=NOW)
    conn.commit()
    row = heartbeat_dao.get(conn, "codex-cli")
    assert row is not None
    assert row.agent == "codex-cli"


def test_get_returns_none_for_unknown(conn):
    assert heartbeat_dao.get(conn, "unknown-agent") is None


def test_get_all_returns_all_agents(conn):
    heartbeat_dao.upsert(conn, agent="claude-code", status="alive", now=NOW)
    heartbeat_dao.upsert(conn, agent="codex-cli", status="alive", now=NOW)
    conn.commit()
    rows = heartbeat_dao.get_all(conn)
    agents = {r.agent for r in rows}
    assert "claude-code" in agents
    assert "codex-cli" in agents


def test_mark_stale_flags_old_rows(conn):
    heartbeat_dao.upsert(conn, agent="claude-code", status="alive", now=NOW)
    conn.commit()
    count = heartbeat_dao.mark_stale(conn, now=LATER)
    conn.commit()
    assert count >= 1
    row = heartbeat_dao.get(conn, "claude-code")
    assert row is not None
    assert row.status == "zombie"


def test_mark_stale_ignores_recent_rows(conn):
    heartbeat_dao.upsert(conn, agent="claude-code", status="alive", now=NOW)
    conn.commit()
    # Only 30s later — not stale
    slightly_later = "2026-05-16T10:00:30Z"
    count = heartbeat_dao.mark_stale(conn, now=slightly_later)
    conn.commit()
    assert count == 0
    row = heartbeat_dao.get(conn, "claude-code")
    assert row is not None
    assert row.status == "alive"


def test_mark_stale_ignores_non_alive_rows(conn):
    heartbeat_dao.upsert(conn, agent="claude-code", status="done", now=NOW)
    conn.commit()
    count = heartbeat_dao.mark_stale(conn, now=LATER)
    assert count == 0
