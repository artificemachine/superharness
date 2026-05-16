"""Tests for task_artifacts table (paperclip.artifacts feature)."""
from __future__ import annotations

import pytest
from superharness.engine.db import get_connection, init_db
from superharness.engine import artifacts_dao


@pytest.fixture
def conn(tmp_path):
    c = get_connection(str(tmp_path))
    init_db(c)
    yield c
    c.close()


NOW = "2026-05-16T10:00:00Z"


def test_add_artifact(conn):
    row = artifacts_dao.add(
        conn,
        task_id="t-abc",
        path="/tmp/output.py",
        agent="claude-code",
        type="code",
        now=NOW,
    )
    assert row.task_id == "t-abc"
    assert row.path == "/tmp/output.py"
    assert row.type == "code"
    assert row.agent == "claude-code"
    assert row.id > 0


def test_add_defaults_type_to_file(conn):
    row = artifacts_dao.add(conn, task_id="t-1", path="/tmp/x.bin", now=NOW)
    assert row.type == "file"


def test_add_normalizes_unknown_type(conn):
    row = artifacts_dao.add(conn, task_id="t-1", path="/tmp/x", type="unknown_type", now=NOW)
    assert row.type == "file"


def test_get_for_task_returns_all(conn):
    artifacts_dao.add(conn, task_id="t-1", path="/tmp/a.py", type="code", now=NOW)
    artifacts_dao.add(conn, task_id="t-1", path="/tmp/b.png", type="image", now=NOW)
    artifacts_dao.add(conn, task_id="t-2", path="/tmp/c.txt", type="file", now=NOW)
    conn.commit()
    rows = artifacts_dao.get_for_task(conn, "t-1")
    assert len(rows) == 2
    paths = {r.path for r in rows}
    assert "/tmp/a.py" in paths
    assert "/tmp/b.png" in paths


def test_get_for_task_empty_when_none(conn):
    rows = artifacts_dao.get_for_task(conn, "nonexistent")
    assert rows == []


def test_add_with_hash_and_size(conn):
    row = artifacts_dao.add(
        conn,
        task_id="t-1",
        path="/tmp/report.md",
        type="test_report",
        hash="abc123",
        size_bytes=1024,
        now=NOW,
    )
    assert row.hash == "abc123"
    assert row.size_bytes == 1024
