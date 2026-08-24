"""Typed boundary tests for `handoffs_dao.append`.

`append` is the single chokepoint every caller (CLI handoff write, MCP,
YAML backfill) goes through to insert a row into `handoffs`. Before this
test file, `phase` and `status` were free-text columns: any string landed
in SQLite unvalidated. This pins the gate: an out-of-set `phase` or
`status` must raise `StateError` before any row is written, and every
member of `tasks_dao.VALID_STATUSES` must still be accepted.

See docs/PLAN-typed-boundaries-context-hashing.md, Iteration 1.
"""

from __future__ import annotations

import pytest

from superharness.engine import handoffs_dao
from superharness.engine.state_errors import StateError
from superharness.engine.tasks_dao import VALID_STATUSES
from superharness.engine.db import get_connection, init_db


def test_import_smoke() -> None:
    import superharness.engine.handoffs_dao  # noqa: F401
    import superharness.commands.handoff_write  # noqa: F401


def _conn(tmp_path):
    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.execute(
        "INSERT OR IGNORE INTO tasks (id, title, status, project_path, created_at, version)"
        " VALUES ('t1', 't1', 'todo', ?, '2026-01-01T00:00:00Z', 1)",
        (str(tmp_path),),
    )
    conn.commit()
    return conn


def test_append_rejects_unknown_phase(tmp_path) -> None:
    conn = _conn(tmp_path)
    with pytest.raises(StateError, match="phase"):
        handoffs_dao.append(
            conn,
            task_id="t1",
            phase="bogus",
            status="report_ready",
            now="2026-01-01T00:00:00Z",
        )
    conn.close()


def test_append_rejects_unknown_status(tmp_path) -> None:
    conn = _conn(tmp_path)
    with pytest.raises(StateError, match="status"):
        handoffs_dao.append(
            conn,
            task_id="t1",
            phase="report",
            status="finished",
            now="2026-01-01T00:00:00Z",
        )
    conn.close()


@pytest.mark.parametrize("status", sorted(VALID_STATUSES))
def test_append_accepts_every_valid_status(tmp_path, status: str) -> None:
    conn = _conn(tmp_path)
    row = handoffs_dao.append(
        conn,
        task_id="t1",
        phase="report",
        status=status,
        now="2026-01-01T00:00:00Z",
    )
    assert row.status == status
    conn.close()


@pytest.mark.parametrize("status", sorted(handoffs_dao.HANDOFF_ONLY_STATUSES))
def test_append_accepts_handoff_only_statuses(tmp_path, status: str) -> None:
    """Regression: engine/discuss.py _do_approve writes "approved" and
    scripts/dashboard-ui.py writes "plan_confirmed"; neither is a task status
    and both were silently dropped by the first version of the gate."""
    conn = _conn(tmp_path)
    row = handoffs_dao.append(
        conn,
        task_id="t1",
        phase="plan",
        status=status,
        now="2026-01-01T00:00:00Z",
    )
    assert row.status == status
    conn.close()


def test_append_accepts_legacy_done_phase(tmp_path) -> None:
    """Regression: close handoffs carry phase="done" (read by inbox_watch)."""
    conn = _conn(tmp_path)
    row = handoffs_dao.append(
        conn, task_id="t1", phase="done", status="done", now="2026-01-01T00:00:00Z"
    )
    assert row.phase == "done"
    conn.close()


def test_rejected_append_writes_no_row(tmp_path) -> None:
    conn = _conn(tmp_path)
    with pytest.raises(StateError):
        handoffs_dao.append(
            conn,
            task_id="t1",
            phase="bogus",
            status="nope",
            now="2026-01-01T00:00:00Z",
        )
    count = conn.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0]
    assert count == 0
    conn.close()


def test_write_handoff_to_db_propagates_state_error(tmp_path) -> None:
    from superharness.engine import state_writer

    project = tmp_path / "project"
    project.mkdir()
    (project / ".superharness").mkdir()

    with pytest.raises(StateError):
        state_writer.write_handoff_to_db(
            str(project),
            {"task": "t1", "status": "nope"},
        )
