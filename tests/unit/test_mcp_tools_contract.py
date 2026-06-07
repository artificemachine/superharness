"""Tests for MCP contract tools — Iteration 5."""
from __future__ import annotations

import pytest
from pathlib import Path

from superharness.mcp.tools.contract import (
    get_contract,
    get_task,
    create_task,
    update_status,
)


def _make_db(tmp_path: Path):
    """Create a real SQLite DB with superharness schema."""
    from superharness.engine import db
    conn = db.get_connection(str(tmp_path))
    db.init_db(conn, str(tmp_path))
    return conn


def test_get_contract_returns_all_tasks(tmp_path):
    conn = _make_db(tmp_path)
    create_task(conn, id="t1", title="Task One", owner="claude-code")
    create_task(conn, id="t2", title="Task Two", owner="codex-cli")
    tasks = get_contract(conn)
    ids = [t["id"] for t in tasks]
    assert "t1" in ids and "t2" in ids


def test_get_task_known_id(tmp_path):
    conn = _make_db(tmp_path)
    create_task(conn, id="task-a", title="Alpha", owner="claude-code")
    result = get_task(conn, "task-a")
    assert result is not None
    assert result["title"] == "Alpha"


def test_get_task_unknown_id_returns_none(tmp_path):
    conn = _make_db(tmp_path)
    result = get_task(conn, "does-not-exist")
    assert result is None


def test_create_task_persists(tmp_path):
    conn = _make_db(tmp_path)
    create_task(conn, id="new-t", title="New Task", owner="gemini-cli")
    result = get_task(conn, "new-t")
    assert result is not None
    assert result["owner"] == "gemini-cli"


def test_update_status_valid_transition(tmp_path):
    conn = _make_db(tmp_path)
    create_task(conn, id="t3", title="Three", owner="claude-code")
    update_status(conn, task_id="t3", status="plan_proposed", actor="claude-code", summary="plan written")
    result = get_task(conn, "t3")
    assert result["status"] == "plan_proposed"


def test_update_status_fires_hook(tmp_path):
    from superharness.mcp.hooks import HookRegistry
    conn = _make_db(tmp_path)
    reg = HookRegistry()
    fired = []
    reg.register("task:completed", lambda p: fired.append(p), project_path=str(tmp_path))
    create_task(conn, id="t4", title="Four", owner="claude-code")
    # Advance to review_passed (legal predecessor of done) via raw SQL to bypass the
    # full lifecycle — this test only checks that the hook fires, not the transition path.
    conn.execute("UPDATE tasks SET status='review_passed' WHERE id='t4'")
    conn.commit()
    update_status(conn, task_id="t4", status="done", actor="claude-code", summary="done",
                  hook_registry=reg, project_path=str(tmp_path))
    assert fired != []


def test_get_contract_empty_db(tmp_path):
    conn = _make_db(tmp_path)
    tasks = get_contract(conn)
    assert tasks == []
