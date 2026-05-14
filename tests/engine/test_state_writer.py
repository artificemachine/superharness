"""Tests for engine.state_writer — RED tests for iter 3a of auto-mode-gap-plan.

iter 3a (skeleton): introduces a unified write API for tasks, inbox items, and
discussion state. Writes go to SQLite first; YAML is queued for export.

The full migration (3b-3e: routing all writers through this module, switching
default backend to sqlite_only) is deferred — see docs/auto-mode-gap-plan.md
for the remaining work.

These tests pin down the public API contract.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def state_writer():
    from superharness.engine import state_writer
    return state_writer


def test_module_exposes_set_task_status(state_writer) -> None:
    assert callable(state_writer.set_task_status)


def test_module_exposes_set_inbox_status(state_writer) -> None:
    assert callable(state_writer.set_inbox_status)


def test_module_exposes_upsert_handoff(state_writer) -> None:
    assert callable(state_writer.upsert_handoff)


def test_set_task_status_writes_through_to_sqlite(state_writer, clean_harness: Path) -> None:
    # Seed a task in YAML so SQLite migration on first read picks it up
    contract = clean_harness / ".superharness" / "contract.yaml"
    import yaml
    contract.write_text(yaml.dump({"tasks": [{"id": "feat.foo", "status": "todo"}]}))

    ok = state_writer.set_task_status(str(clean_harness), "feat.foo", "plan_proposed")
    assert ok is True

    # Verify by reading back through state_reader (the public read path)
    from superharness.engine.state_reader import get_tasks
    tasks = get_tasks(str(clean_harness))
    foo = next((t for t in tasks if t.get("id") == "feat.foo"), None)
    assert foo is not None
    assert foo.get("status") == "plan_proposed"


def test_set_inbox_status_writes_through(state_writer, clean_harness: Path) -> None:
    from superharness.engine.db import get_connection, init_db, transaction
    from superharness.engine import inbox_dao, tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(clean_harness))
    init_db(conn)
    with transaction(conn):
        tasks_dao.upsert(conn, TaskRow(
            id="feat.foo", title="feat.foo", owner="claude-code", status="todo",
            effort=None, project_path=None, development_method=None,
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None,
            version=1, created_at="2026-04-27T12:00:00Z",
        ))
        inbox_dao.enqueue(
            conn, id="test-1", task_id="feat.foo", target_agent="claude-code",
            project_path=str(clean_harness), now="2026-04-27T12:00:00Z",
        )
    conn.close()

    ok = state_writer.set_inbox_status(str(clean_harness), "test-1", "paused")
    assert ok is True

    # Verify by reading back through the public read path
    from superharness.engine.state_reader import get_inbox_items
    items = get_inbox_items(str(clean_harness))
    item = next((i for i in items if i.get("id") == "test-1"), None)
    assert item is not None
    assert item["status"] == "paused"


def test_set_task_status_handles_unknown_task_gracefully(state_writer, clean_harness: Path) -> None:
    """Unknown task id returns False, does not raise."""
    ok = state_writer.set_task_status(str(clean_harness), "nonexistent.task", "done")
    assert ok is False


def test_set_inbox_status_handles_unknown_id_gracefully(state_writer, clean_harness: Path) -> None:
    ok = state_writer.set_inbox_status(str(clean_harness), "nonexistent", "paused")
    assert ok is False
