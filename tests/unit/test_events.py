"""Tests for engine.events — typed telemetry events table (migration v31) +
background emitter whose failures never disturb business logic.

Distinct from (and additive to) engine/event_stream.py, which appends
free-form JSONL events to `.superharness/events.jsonl`. This module is the
typed, queryable SQLite counterpart.

See docs/PLAN-steal-omnigent.md iteration 4.
"""
from __future__ import annotations

import json
import logging

from superharness.engine.db import get_connection, init_db


def test_migration_v31_creates_events_table(tmp_path):
    conn = get_connection(str(tmp_path))
    try:
        init_db(conn)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
        assert {"id", "ts", "kind", "task_id", "payload_json"} <= cols
    finally:
        conn.close()


def test_emit_task_transition_lands_in_db(tmp_path):
    from superharness.engine import events

    project_dir = str(tmp_path)
    conn = get_connection(project_dir)
    init_db(conn)
    conn.close()

    events.configure(project_dir)
    events.emit(events.TaskTransition(task_id="t1", from_status="todo", to_status="in_progress"))
    assert events.flush(timeout=5) is True

    conn = get_connection(project_dir)
    try:
        row = conn.execute(
            "SELECT kind, task_id, payload_json FROM events WHERE kind = 'task_transition'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["task_id"] == "t1"
    payload = json.loads(row["payload_json"])
    assert payload["from_status"] == "todo"
    assert payload["to_status"] == "in_progress"


def test_emitter_failure_never_raises(monkeypatch, tmp_path, caplog):
    from superharness.engine import events

    def _raise(*args, **kwargs):
        raise RuntimeError("db unavailable")

    # logging_utils.get_logger() sets logging.getLogger("superharness")
    # .propagate = False the first time ANY superharness.* logger is used
    # (process-wide, cached on the Logger singleton). If an earlier test in
    # the same pytest process triggered that, records from
    # superharness.engine.events stop reaching caplog's root-attached
    # handler even though they're still logged. Force propagation back on
    # for the duration of this assertion.
    monkeypatch.setattr(logging.getLogger("superharness"), "propagate", True)

    events.configure(str(tmp_path))
    monkeypatch.setattr("superharness.engine.db.get_connection", _raise)

    with caplog.at_level(logging.WARNING):
        events.emit(events.TaskTransition(task_id="t1", from_status="todo", to_status="in_progress"))
        assert events.flush(timeout=5) is True

    assert any(rec.levelno == logging.WARNING for rec in caplog.records)


def test_set_task_status_emits_transition(clean_harness):
    from superharness.engine import events, tasks_dao, state_writer

    project_dir = str(clean_harness)
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        row = tasks_dao.TaskRow(
            id="t1", title="T", owner="claude-code", status="todo",
            effort=None, project_path=project_dir, development_method=None,
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-01-01T00:00:00Z", blocked_by=[],
        )
        tasks_dao.upsert(conn, row)
        conn.commit()
    finally:
        conn.close()

    events.configure(project_dir)
    ok = state_writer.set_task_status(project_dir, "t1", "plan_proposed", force=True)
    assert ok is True
    assert events.flush(timeout=5) is True

    conn = get_connection(project_dir)
    try:
        row = conn.execute(
            "SELECT kind, task_id, payload_json FROM events "
            "WHERE kind = 'task_transition' AND task_id = 't1'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["to_status"] == "plan_proposed"


def test_events_json_payload_is_valid(tmp_path):
    from superharness.engine import events

    project_dir = str(tmp_path)
    conn = get_connection(project_dir)
    init_db(conn)
    conn.close()

    events.configure(project_dir)
    events.emit(events.DispatchStarted(task_id="t1", agent="claude-code"))
    events.emit(events.DispatchFinished(task_id="t1", agent="claude-code", duration_s=1.5, exit_code=0))
    assert events.flush(timeout=5) is True

    conn = get_connection(project_dir)
    try:
        rows = conn.execute("SELECT payload_json FROM events").fetchall()
    finally:
        conn.close()
    assert len(rows) >= 2
    for r in rows:
        json.loads(r["payload_json"])  # must not raise
