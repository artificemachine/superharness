"""TDD: workflow/autonomy/require_tdd must survive the upsert round-trip.

Bug: _task_row_from_dict in contract_io.py does not pass workflow/autonomy/
require_tdd to TaskRow, and tasks_dao.upsert does not include those columns in
its INSERT or ON CONFLICT UPDATE. The columns stay NULL in SQLite regardless
of what was written to the task dict or TaskRow.

Fix: propagate all three fields through _task_row_from_dict and upsert.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest


def _make_db(tmp_path: Path):
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(tmp_path))
    init_db(conn)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestWorkflowColumnPersistence:
    def test_upsert_persists_workflow(self, tmp_path):
        """tasks_dao.upsert must write workflow to SQLite and get() must return it."""
        from superharness.engine import tasks_dao

        conn = _make_db(tmp_path)
        now = _now()
        row = tasks_dao.TaskRow(
            id="task.workflow-persist", title="t", owner="claude-code",
            status="todo", effort="medium", project_path=str(tmp_path),
            development_method=None, acceptance_criteria=[], test_types=[],
            out_of_scope=[], definition_of_done=[], context=None, tdd=None,
            version=1, created_at=now, workflow="quick",
        )
        tasks_dao.upsert(conn, row)
        conn.commit()

        fetched = tasks_dao.get(conn, "task.workflow-persist")
        conn.close()
        assert fetched is not None
        assert fetched.workflow == "quick", (
            f"expected workflow='quick', got {fetched.workflow!r}"
        )

    def test_upsert_persists_autonomy(self, tmp_path):
        from superharness.engine import tasks_dao

        conn = _make_db(tmp_path)
        now = _now()
        row = tasks_dao.TaskRow(
            id="task.autonomy-persist", title="t", owner="claude-code",
            status="todo", effort="medium", project_path=str(tmp_path),
            development_method=None, acceptance_criteria=[], test_types=[],
            out_of_scope=[], definition_of_done=[], context=None, tdd=None,
            version=1, created_at=now, autonomy="ai_driven",
        )
        tasks_dao.upsert(conn, row)
        conn.commit()

        fetched = tasks_dao.get(conn, "task.autonomy-persist")
        conn.close()
        assert fetched is not None
        assert fetched.autonomy == "ai_driven"

    def test_upsert_persists_require_tdd(self, tmp_path):
        from superharness.engine import tasks_dao

        conn = _make_db(tmp_path)
        now = _now()
        row = tasks_dao.TaskRow(
            id="task.tdd-persist", title="t", owner="claude-code",
            status="todo", effort="medium", project_path=str(tmp_path),
            development_method=None, acceptance_criteria=[], test_types=[],
            out_of_scope=[], definition_of_done=[], context=None, tdd=None,
            version=1, created_at=now, require_tdd=True,
        )
        tasks_dao.upsert(conn, row)
        conn.commit()

        fetched = tasks_dao.get(conn, "task.tdd-persist")
        conn.close()
        assert fetched is not None
        assert fetched.require_tdd is True

    def test_upsert_update_preserves_workflow(self, tmp_path):
        """ON CONFLICT update path must also write workflow (not revert to NULL)."""
        from superharness.engine import tasks_dao

        conn = _make_db(tmp_path)
        now = _now()
        row = tasks_dao.TaskRow(
            id="task.update-workflow", title="t", owner="claude-code",
            status="todo", effort="medium", project_path=str(tmp_path),
            development_method=None, acceptance_criteria=[], test_types=[],
            out_of_scope=[], definition_of_done=[], context=None, tdd=None,
            version=1, created_at=now, workflow="implementation",
        )
        tasks_dao.upsert(conn, row)
        conn.commit()

        # Second upsert (same id → triggers ON CONFLICT path)
        row2 = tasks_dao.TaskRow(
            id="task.update-workflow", title="updated", owner="claude-code",
            status="in_progress", effort="medium", project_path=str(tmp_path),
            development_method=None, acceptance_criteria=[], test_types=[],
            out_of_scope=[], definition_of_done=[], context=None, tdd=None,
            version=1, created_at=now, workflow="implementation",
        )
        tasks_dao.upsert(conn, row2)
        conn.commit()

        fetched = tasks_dao.get(conn, "task.update-workflow")
        conn.close()
        assert fetched is not None
        assert fetched.workflow == "implementation"

    def test_task_row_from_dict_passes_workflow(self, tmp_path):
        """_task_row_from_dict must propagate workflow from the input dict."""
        from superharness.engine.contract_io import _task_row_from_dict

        t = {
            "id": "task.dict-workflow",
            "title": "test",
            "owner": "claude-code",
            "status": "todo",
            "workflow": "note",
        }
        row = _task_row_from_dict(t, str(tmp_path), _now())
        assert row.workflow == "note", (
            f"_task_row_from_dict dropped workflow; got {row.workflow!r}"
        )

    def test_task_row_from_dict_passes_autonomy(self, tmp_path):
        from superharness.engine.contract_io import _task_row_from_dict

        t = {
            "id": "task.dict-autonomy",
            "title": "test",
            "owner": "claude-code",
            "status": "todo",
            "autonomy": "manual",
        }
        row = _task_row_from_dict(t, str(tmp_path), _now())
        assert row.autonomy == "manual"

    def test_task_row_from_dict_passes_require_tdd(self, tmp_path):
        from superharness.engine.contract_io import _task_row_from_dict

        t = {
            "id": "task.dict-tdd",
            "title": "test",
            "owner": "claude-code",
            "status": "todo",
            "require_tdd": True,
        }
        row = _task_row_from_dict(t, str(tmp_path), _now())
        assert row.require_tdd is True
