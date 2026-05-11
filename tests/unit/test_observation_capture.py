"""Tests for engine.observation_capture.

Closes the claude-mem-style loop: when a task reaches report_ready, build
a context dict from task + latest report handoff, run it through the
selected summarizer, and insert the result into task_observations.

The capture is defensive: any internal exception returns None and never
raises, so a transition cannot be broken by a summarizer fault.
"""
from __future__ import annotations

import pytest

from superharness.engine.db import get_connection, init_db, now_iso
from superharness.engine import handoffs_dao, observations_dao, tasks_dao
from superharness.engine.observation_capture import capture_observation
from superharness.engine.summarizer import NoopSummarizer


def _seed_task(conn, task_id: str = "t-1", title: str = "Sample task"):
    now = now_iso()
    conn.execute(
        """
        INSERT INTO tasks (id, title, status, version, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (task_id, title, "report_ready", 1, now),
    )
    conn.commit()


@pytest.fixture
def conn(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    c = get_connection(str(project_dir))
    init_db(c, str(project_dir))
    yield c
    c.close()


def test_capture_inserts_observation(conn):
    _seed_task(conn)
    handoffs_dao.append(
        conn,
        task_id="t-1",
        phase="report",
        status="report_ready",
        from_agent="claude-code",
        to_agent="owner",
        content="Did the thing. All tests pass.",
        now=now_iso(),
    )

    obs_id = capture_observation(conn, "t-1", "report_ready", summarizer=NoopSummarizer())
    assert obs_id is not None and obs_id > 0

    row = observations_dao.get_by_id(conn, obs_id)
    assert row is not None
    assert row["task_id"] == "t-1"
    assert row["phase"] == "report_ready"
    assert "Did the thing" in row["summary"]


def test_capture_works_without_report_handoff(conn):
    _seed_task(conn)
    obs_id = capture_observation(conn, "t-1", "report_ready", summarizer=NoopSummarizer())
    assert obs_id is not None
    row = observations_dao.get_by_id(conn, obs_id)
    assert "t-1" in row["summary"]


def test_capture_returns_none_for_unknown_task(conn):
    obs_id = capture_observation(conn, "nope", "report_ready", summarizer=NoopSummarizer())
    assert obs_id is None


def test_capture_swallows_summarizer_exception(conn):
    _seed_task(conn)

    class Boom:
        def summarize(self, context):
            raise RuntimeError("provider down")

    obs_id = capture_observation(conn, "t-1", "report_ready", summarizer=Boom())
    assert obs_id is None


def test_capture_strips_private_tags_from_handoff(conn):
    _seed_task(conn)
    handoffs_dao.append(
        conn,
        task_id="t-1",
        phase="report",
        status="report_ready",
        from_agent="claude-code",
        to_agent="owner",
        content="public <private>OPENAI_KEY=sk-leak</private> stuff",
        now=now_iso(),
    )
    obs_id = capture_observation(conn, "t-1", "report_ready", summarizer=NoopSummarizer())
    assert obs_id is not None
    row = observations_dao.get_by_id(conn, obs_id)
    assert "sk-leak" not in row["summary"]
    assert "<private>" not in row["summary"]


def test_capture_default_summarizer_when_none_passed(conn):
    _seed_task(conn)
    obs_id = capture_observation(conn, "t-1", "report_ready")
    assert obs_id is not None
