"""Integration-flavoured unit test: transitioning a task to report_ready
through set_task_status auto-captures an observation snapshot.

Verifies the wire-up in engine.state_writer without exercising the full
CLI surface. The hook is defensive: if capture fails internally the
transition itself still succeeds.
"""
from __future__ import annotations

import pytest
from unittest import mock

from superharness.engine.db import get_connection, init_db, now_iso
from superharness.engine import observations_dao, handoffs_dao
from superharness.engine.state_writer import set_task_status


def _seed_task(project_dir: str, task_id: str = "t-1"):
    conn = get_connection(project_dir)
    try:
        init_db(conn, project_dir)
        conn.execute(
            """
            INSERT INTO tasks (id, title, status, version, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, "sample", "in_progress", 1, now_iso()),
        )
        conn.execute(
            "UPDATE tasks SET in_progress_at = ? WHERE id = ?",
            (now_iso(), task_id),
        )
        handoffs_dao.append(
            conn,
            task_id=task_id,
            phase="report",
            status="report_ready",
            from_agent="claude-code",
            to_agent="owner",
            content="task done; tests pass",
            now=now_iso(),
        )
        conn.commit()
    finally:
        conn.close()


def test_transition_to_report_ready_captures_observation(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    _seed_task(str(project_dir), "t-1")

    from superharness.engine.summarizer import NoopSummarizer
    with mock.patch("superharness.engine.observation_capture.get_summarizer", return_value=NoopSummarizer()):
        ok = set_task_status(str(project_dir), "t-1", "report_ready", force=True)
        assert ok is True

    conn = get_connection(str(project_dir))
    try:
        rows = observations_dao.list_for_task(conn, "t-1")
        assert len(rows) == 1
        assert rows[0]["phase"] == "report_ready"
        assert "t-1" in rows[0]["summary"]
    finally:
        conn.close()


def test_transition_to_other_status_does_not_capture(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    _seed_task(str(project_dir))

    ok = set_task_status(str(project_dir), "t-1", "in_progress", force=True)
    assert ok is True

    conn = get_connection(str(project_dir))
    try:
        rows = observations_dao.list_for_task(conn, "t-1")
        assert rows == []
    finally:
        conn.close()


def test_capture_failure_does_not_break_transition(tmp_path, monkeypatch):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    _seed_task(str(project_dir))

    def _boom(*_a, **_kw):
        raise RuntimeError("capture broke")

    monkeypatch.setattr(
        "superharness.engine.observation_capture.capture_observation",
        _boom,
    )

    ok = set_task_status(str(project_dir), "t-1", "report_ready", force=True)
    assert ok is True
