"""Chaos test: a DB outage during background event write must still only
warn, never raise, for a *valid* event — proving the new emit()-time
validation (Iteration 2) did not change that contract.

Mirrors tests/unit/test_events.py::test_emitter_failure_never_raises.
See docs/PLAN-typed-boundaries-context-hashing.md, Iteration 2.
"""

from __future__ import annotations

import logging


def test_db_failure_still_only_warns_after_validation(monkeypatch, tmp_path, caplog):
    from superharness.engine import events

    def _raise(*args, **kwargs):
        raise RuntimeError("db unavailable")

    events.configure(str(tmp_path))
    monkeypatch.setattr("superharness.engine.db.get_connection", _raise)

    valid_event = events.TaskTransition(
        task_id="t1", from_status="todo", to_status="in_progress"
    )

    with caplog.at_level(logging.WARNING):
        events.emit(valid_event)
        assert events.flush(timeout=5) is True

    assert any(rec.levelno == logging.WARNING for rec in caplog.records)
