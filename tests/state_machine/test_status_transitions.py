"""Iter 9 RED: CLI and MCP must funnel status writes through validate_status_transition.

These tests verify that invalid transitions (e.g. todo→done) are rejected by both
the CLI path (task.py:status_update) and the MCP path (mcp/tools/contract.py:update_status).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest


# ── helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _setup_project(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    """Create .superharness/ dir + initialised SQLite DB. Returns (project_dir, conn)."""
    harness = tmp_path / ".superharness"
    harness.mkdir()
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(tmp_path))
    init_db(conn)
    return tmp_path, conn


def _insert_task(conn: sqlite3.Connection, task_id: str, status: str, owner: str = "claude-code") -> None:
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at, updated_at, "
        "acceptance_criteria, test_types, out_of_scope, definition_of_done) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (task_id, f"Task {task_id}", owner, status, _now(), _now(), "[]", "[]", "[]", "[]"),
    )
    conn.commit()


# ── Smoke ─────────────────────────────────────────────────────────────────────

def test_validate_status_transition_importable():
    from superharness.engine.next_action import validate_status_transition
    assert callable(validate_status_transition)


def test_task_status_update_importable():
    from superharness.commands.task import status_update
    assert callable(status_update)


def test_mcp_update_status_importable():
    from superharness.mcp.tools.contract import update_status
    assert callable(update_status)


# ── Iter 9 RED: CLI rejects todo→done ────────────────────────────────────────

def test_cli_rejects_todo_to_done(tmp_path):
    """status_update must reject the illegal todo→done transition via validate_status_transition.

    RED: currently status_update only does membership-check, not graph validation.
    It will write the transition without raising. The test fails until the fix lands.
    """
    project, conn = _setup_project(tmp_path)
    _insert_task(conn, "t-cli-trans", "todo", owner="claude-code")
    conn.close()

    from superharness.commands.task import status_update
    with pytest.raises(SystemExit) as exc_info:
        status_update(
            str(project),
            "t-cli-trans",
            "done",
            "claude-code",
            summary="completed",  # bypass the missing-summary early abort
        )
    assert exc_info.value.code == 2, (
        f"Expected SystemExit(2) for illegal todo→done transition, "
        f"got SystemExit({exc_info.value.code})"
    )


# ── Iter 9 RED: MCP rejects invalid transition ────────────────────────────────

def test_mcp_rejects_invalid_transition(tmp_path):
    """update_status (MCP) must reject illegal transitions.

    RED: currently update_status does a raw SQL UPDATE with no transition guard.
    It returns the updated task dict on success. The test fails until the fix adds
    validate_status_transition and returns {} on rejection.
    """
    _, conn = _setup_project(tmp_path)
    _insert_task(conn, "t-mcp-trans", "todo", owner="claude-code")

    from superharness.mcp.tools.contract import update_status
    result = update_status(
        conn,
        task_id="t-mcp-trans",
        status="done",
        actor="claude-code",
        summary="completed",
    )
    conn.close()

    assert result == {}, (
        "MCP update_status must return {} for illegal todo→done transition. "
        "Add validate_status_transition check before the SQL UPDATE."
    )


# ── Unit: valid transition passes CLI ────────────────────────────────────────

def test_cli_allows_valid_transition(tmp_path):
    """todo→plan_proposed is a legal first step and must succeed."""
    project, conn = _setup_project(tmp_path)
    _insert_task(conn, "t-cli-valid", "todo", owner="claude-code")
    conn.close()

    from superharness.commands.task import status_update
    rc = status_update(
        str(project),
        "t-cli-valid",
        "plan_proposed",
        "claude-code",
        summary="plan ready",
    )
    assert rc == 0, f"Expected rc=0 for valid todo→plan_proposed, got {rc}"


# ── Unit: valid transition passes MCP ────────────────────────────────────────

def test_mcp_allows_valid_transition(tmp_path):
    """MCP update_status must succeed on a legal transition."""
    _, conn = _setup_project(tmp_path)
    _insert_task(conn, "t-mcp-valid", "todo", owner="claude-code")

    from superharness.mcp.tools.contract import update_status
    result = update_status(
        conn,
        task_id="t-mcp-valid",
        status="plan_proposed",
        actor="claude-code",
        summary="plan ready",
    )
    conn.close()

    assert result != {}, (
        "MCP update_status must return the updated task on a valid todo→plan_proposed transition."
    )
    assert result.get("status") == "plan_proposed", (
        f"Expected status=plan_proposed, got {result.get('status')!r}"
    )


# ── Regression: state_writer already validates ────────────────────────────────

def test_state_writer_already_uses_validate():
    """state_writer.set_task_status already validates — confirm structural presence."""
    import inspect
    from superharness.engine import state_writer
    src = inspect.getsource(state_writer.set_task_status)
    assert "validate_status_transition" in src, (
        "state_writer.set_task_status must call validate_status_transition"
    )


# ── Regression: both writers reject same illegal move ────────────────────────

def test_cli_and_mcp_both_reject_done_from_todo(tmp_path):
    """CLI and MCP must both block the same illegal transition (divergent-writer regression)."""
    project, conn = _setup_project(tmp_path)
    _insert_task(conn, "t-cli-reg", "todo", owner="claude-code")
    _insert_task(conn, "t-mcp-reg", "todo", owner="claude-code")
    conn.close()

    # CLI rejects
    from superharness.commands.task import status_update
    with pytest.raises(SystemExit) as cli_exc:
        status_update(str(project), "t-cli-reg", "done", "claude-code", summary="done")
    assert cli_exc.value.code == 2

    # MCP rejects
    from superharness.engine.db import get_connection, init_db
    conn2 = get_connection(str(project))
    init_db(conn2)
    from superharness.mcp.tools.contract import update_status
    mcp_result = update_status(conn2, task_id="t-mcp-reg", status="done",
                               actor="claude-code", summary="done")
    conn2.close()
    assert mcp_result == {}, "MCP must also reject todo→done"
