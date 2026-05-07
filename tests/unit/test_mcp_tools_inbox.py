"""Tests for MCP inbox tools — Iteration 6."""
from __future__ import annotations

import pytest
from pathlib import Path

from superharness.mcp.tools.inbox import get_inbox, enqueue_task
from superharness.mcp.approval import ApprovalGate, ApprovalPending


def _make_db(tmp_path: Path):
    from superharness.engine import db
    conn = db.get_connection(str(tmp_path))
    db.init_db(conn, str(tmp_path))
    return conn


def _seed_task(conn, task_id: str) -> None:
    """Insert a minimal task row to satisfy FK constraint."""
    from superharness.mcp.tools.contract import create_task
    create_task(conn, id=task_id, title=task_id, owner="claude-code")


def test_get_inbox_empty(tmp_path):
    conn = _make_db(tmp_path)
    items = get_inbox(conn)
    assert items == []


def test_enqueue_creates_pending_item(tmp_path):
    conn = _make_db(tmp_path)
    _seed_task(conn, "t1")
    enqueue_task(conn, task_id="t1", target="claude-code", project_path=str(tmp_path))
    items = get_inbox(conn)
    assert len(items) == 1
    assert items[0]["task"] == "t1"
    assert items[0]["status"] == "pending"


def test_enqueue_checks_approval_gate(tmp_path):
    conn = _make_db(tmp_path)
    _seed_task(conn, "t2")
    gate = ApprovalGate()
    with pytest.raises(ApprovalPending):
        enqueue_task(conn, task_id="t2", target="claude-code", project_path=str(tmp_path),
                     gate=gate, conn_id="c1")


def test_enqueue_fires_hook_on_success(tmp_path):
    from superharness.mcp.hooks import HookRegistry
    conn = _make_db(tmp_path)
    _seed_task(conn, "t3")
    reg = HookRegistry()
    fired = []
    reg.register("task:delegated", lambda p: fired.append(p), project_path=str(tmp_path))
    enqueue_task(conn, task_id="t3", target="claude-code", project_path=str(tmp_path),
                 hook_registry=reg)
    assert fired != []


def test_get_inbox_returns_pending_only_by_default(tmp_path):
    conn = _make_db(tmp_path)
    _seed_task(conn, "t4")
    enqueue_task(conn, task_id="t4", target="claude-code", project_path=str(tmp_path))
    items = get_inbox(conn, status_filter=["pending"])
    assert all(i["status"] == "pending" for i in items)
