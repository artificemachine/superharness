"""Unit tests for engine.context_dao — content-addressed prompt components.

See docs/PLAN-typed-boundaries-context-hashing.md, Iteration 3.
"""

from __future__ import annotations

import hashlib

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine.state_errors import StateError
from superharness.engine import context_dao


@pytest.fixture
def conn(tmp_path):
    c = get_connection(str(tmp_path))
    init_db(c)
    yield c
    c.close()


def test_record_component_returns_sha256_of_content(conn):
    result = context_dao.record_component(
        conn, component_type="task_instructions", content="abc"
    )
    assert result == hashlib.sha256(b"abc").hexdigest()


def test_same_content_stored_once(conn):
    context_dao.record_component(conn, component_type="task_instructions", content="abc")
    context_dao.record_component(conn, component_type="task_instructions", content="abc")
    count = conn.execute("SELECT COUNT(*) FROM context_component").fetchone()[0]
    assert count == 1


def test_record_dispatch_preserves_order(conn):
    dispatch_id = context_dao.record_dispatch(
        conn,
        task_id="t1",
        agent="claude-code",
        components=[("system", "a"), ("task_instructions", "b")],
        now="2026-08-23T00:00:00Z",
    )
    assert isinstance(dispatch_id, int)

    rows = context_dao.components_for_dispatch(conn, dispatch_id)
    assert rows == [
        (0, "system", hashlib.sha256(b"a").hexdigest()),
        (1, "task_instructions", hashlib.sha256(b"b").hexdigest()),
    ]


def test_last_two_dispatches_for_task(conn):
    ids = []
    for i in range(3):
        dispatch_id = context_dao.record_dispatch(
            conn,
            task_id="t1",
            agent="claude-code",
            components=[("system", f"content-{i}")],
            now=f"2026-08-23T00:0{i}:00Z",
        )
        ids.append(dispatch_id)

    result = context_dao.last_dispatches(conn, task_id="t1", n=2)
    assert result == [ids[2], ids[1]]


def test_record_component_rejects_unknown_type(conn):
    with pytest.raises(StateError):
        context_dao.record_component(conn, component_type="lunch", content="abc")
