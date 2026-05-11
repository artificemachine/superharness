"""Tests for engine.observations_dao and migration v13.

Storage layer for task observation snapshots. Foundational piece for the
claude-mem-style observation-at-report_ready feature. The auto-capture
hook and the LLM summarizer adapter are not in this iteration: the DAO
just stores pre-built summary text addressed by task id.
"""
from __future__ import annotations

import sqlite3

import pytest

from superharness.engine.db import get_connection, init_db, CURRENT_SCHEMA_VERSION
from superharness.engine import observations_dao


@pytest.fixture
def conn(tmp_path):
    """A fresh project dir with an initialised state DB."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    c = get_connection(str(project_dir))
    init_db(c, str(project_dir))
    yield c
    c.close()


def test_schema_is_at_v13(conn):
    assert CURRENT_SCHEMA_VERSION >= 13
    cur = conn.execute("PRAGMA user_version")
    assert cur.fetchone()[0] >= 13


def test_task_observations_table_exists(conn):
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='task_observations'"
    )
    assert cur.fetchone() is not None


def test_task_observations_has_expected_columns(conn):
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(task_observations)")}
    assert {"id", "task_id", "phase", "summary", "created_at"}.issubset(cols)


def test_task_observations_index_on_task_id(conn):
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='task_observations'"
    )
    names = {row["name"] for row in cur.fetchall()}
    assert any("task_id" in n for n in names), names


def test_insert_returns_id(conn):
    new_id = observations_dao.insert(conn, "task-1", "report_ready", "did stuff")
    assert isinstance(new_id, int) and new_id > 0


def test_get_by_id_roundtrip(conn):
    new_id = observations_dao.insert(conn, "task-1", "report_ready", "did stuff")
    row = observations_dao.get_by_id(conn, new_id)
    assert row is not None
    assert row["task_id"] == "task-1"
    assert row["phase"] == "report_ready"
    assert row["summary"] == "did stuff"
    assert row["id"] == new_id
    assert row["created_at"]


def test_get_by_id_missing_returns_none(conn):
    assert observations_dao.get_by_id(conn, 9999) is None


def test_list_for_task_empty(conn):
    assert observations_dao.list_for_task(conn, "nope") == []


def test_list_for_task_returns_only_matching_task(conn):
    observations_dao.insert(conn, "task-a", "report_ready", "A1")
    observations_dao.insert(conn, "task-b", "report_ready", "B1")
    observations_dao.insert(conn, "task-a", "report_ready", "A2")

    rows = observations_dao.list_for_task(conn, "task-a")
    summaries = [r["summary"] for r in rows]
    assert set(summaries) == {"A1", "A2"}


def test_list_for_task_ordered_by_created_at(conn):
    id1 = observations_dao.insert(conn, "task-1", "report_ready", "first")
    id2 = observations_dao.insert(conn, "task-1", "report_ready", "second")
    rows = observations_dao.list_for_task(conn, "task-1")
    assert [r["id"] for r in rows] == [id1, id2]


def test_insert_strips_private_tags(conn):
    summary = "ok <private>secret</private> public"
    new_id = observations_dao.insert(conn, "task-1", "report_ready", summary)
    row = observations_dao.get_by_id(conn, new_id)
    assert "secret" not in row["summary"]
    assert "<private>" not in row["summary"]


def test_insert_empty_summary_rejected(conn):
    with pytest.raises(ValueError):
        observations_dao.insert(conn, "task-1", "report_ready", "")


def test_insert_requires_task_id(conn):
    with pytest.raises(ValueError):
        observations_dao.insert(conn, "", "report_ready", "stuff")


def test_migration_idempotent(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    c1 = get_connection(str(project_dir))
    init_db(c1, str(project_dir))
    c1.close()

    c2 = get_connection(str(project_dir))
    init_db(c2, str(project_dir))
    cur = c2.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='task_observations'"
    )
    assert cur.fetchone() is not None
    c2.close()
