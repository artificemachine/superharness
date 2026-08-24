"""Tests for the typed event boundary: events.emit() validates its payload
synchronously (TypeError/ValueError) before anything reaches the background
queue, while a DB failure during background write remains warn-only.

See docs/PLAN-typed-boundaries-context-hashing.md, Iteration 2.
"""

from __future__ import annotations

import pytest

from superharness.engine import events
from superharness.engine.db import get_connection, init_db


def test_import_smoke():
    from superharness.engine import events

    assert callable(events.validate_event)


def test_emit_rejects_non_event_object():
    from superharness.engine import events

    with pytest.raises(TypeError):
        events.emit({"kind": "task_transition"})


def test_emit_rejects_wrong_field_type():
    from superharness.engine import events

    bad = events.DispatchFinished(
        task_id="t1", agent="claude-code", duration_s="fast", exit_code=0
    )
    with pytest.raises(TypeError, match="duration_s"):
        events.emit(bad)


def test_emit_rejects_empty_task_id():
    from superharness.engine import events

    bad = events.TaskTransition(task_id="", from_status="todo", to_status="in_progress")
    with pytest.raises(ValueError):
        events.emit(bad)


@pytest.mark.parametrize(
    "event_factory",
    [
        lambda: events.TaskTransition(
            task_id="t1", from_status="todo", to_status="in_progress"
        ),
        lambda: events.DispatchStarted(task_id="t1", agent="claude-code"),
        lambda: events.DispatchFinished(
            task_id="t1", agent="claude-code", duration_s=1.5, exit_code=0
        ),
    ],
)
def test_validate_event_accepts_all_kinds(event_factory):
    event = event_factory()
    assert events.validate_event(event) is None


def test_rejected_event_never_reaches_queue(tmp_path):
    from superharness.engine import events

    project_dir = str(tmp_path)
    conn = get_connection(project_dir)
    init_db(conn)
    conn.close()

    events.configure(project_dir)

    bad = events.TaskTransition(task_id="", from_status="todo", to_status="in_progress")
    with pytest.raises(ValueError):
        events.emit(bad)

    assert events.flush(timeout=5) is True

    conn = get_connection(project_dir)
    try:
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def test_validate_event_accepts_foreign_frozen_dataclass() -> None:
    """Regression: engine/transcript_tail.TranscriptProgress is emitted via
    events.emit() but is not in the Event union; the boundary is structural."""
    from superharness.engine.transcript_tail import TranscriptProgress

    events.validate_event(TranscriptProgress(task_id="t1", line_kind="tool_use"))


def test_validate_event_rejects_dataclass_without_kind() -> None:
    import dataclasses

    @dataclasses.dataclass(frozen=True)
    class NotAnEvent:
        task_id: str

    with pytest.raises(TypeError):
        events.validate_event(NotAnEvent(task_id="t1"))
