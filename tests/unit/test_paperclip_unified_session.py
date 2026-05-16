"""Tests for unified session model — discussions write shadow inbox rows."""
from __future__ import annotations

import pytest
from superharness.engine.db import get_connection, init_db
from superharness.engine import inbox_dao


@pytest.fixture
def conn(tmp_path):
    c = get_connection(str(tmp_path))
    init_db(c)
    # Discussion shadow entries don't map to task rows — disable FK for these tests
    c.execute("PRAGMA foreign_keys=OFF")
    yield c
    c.close()


NOW = "2026-05-16T10:00:00Z"


def test_enqueue_with_discussion_type(conn):
    row = inbox_dao.enqueue(
        conn,
        id="disc-1-r1-claude",
        task_id="discuss-abc/round-1",
        target_agent="claude-code",
        type="discussion",
        now=NOW,
    )
    assert row.id == "disc-1-r1-claude"
    # Verify the type column is stored
    raw = conn.execute("SELECT type FROM inbox WHERE id=?", ("disc-1-r1-claude",)).fetchone()
    assert raw is not None
    assert raw["type"] == "discussion"


def test_enqueue_default_type_is_task(conn):
    row = inbox_dao.enqueue(
        conn,
        id="task-item-1",
        task_id="t-abc",
        target_agent="claude-code",
        now=NOW,
    )
    raw = conn.execute("SELECT type FROM inbox WHERE id=?", ("task-item-1",)).fetchone()
    assert raw is not None
    assert raw["type"] == "task"


def test_discussion_shadow_visible_in_inbox(conn):
    """Discussion shadow entries should appear in standard inbox queries."""
    inbox_dao.enqueue(
        conn,
        id="disc-shadow-1",
        task_id="discuss-xyz/round-1",
        target_agent="codex-cli",
        type="discussion",
        now=NOW,
    )
    conn.commit()
    rows = inbox_dao.get_all(conn)
    ids = [r.id for r in rows]
    assert "disc-shadow-1" in ids
