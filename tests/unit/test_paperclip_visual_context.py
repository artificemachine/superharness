"""Tests for visual_context in adapter payload (paperclip.visual-context feature)."""
from __future__ import annotations

import json

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine import tasks_dao
from superharness.engine.tasks_dao import TaskRow


NOW = "2026-05-16T10:00:00Z"


@pytest.fixture
def project_dir(tmp_path):
    sh = tmp_path / ".superharness"
    sh.mkdir()
    return tmp_path


@pytest.fixture
def conn(project_dir):
    c = get_connection(str(project_dir))
    init_db(c)
    yield c
    c.close()


def _make_task(conn, task_id: str, visual_context: list | None = None):
    extras = {}
    if visual_context is not None:
        extras["visual_context"] = visual_context
    row = TaskRow(
        id=task_id,
        title="Test task",
        owner="claude-code",
        status="todo",
        effort=None,
        project_path="/tmp/proj",
        development_method=None,
        acceptance_criteria=[],
        test_types=[],
        out_of_scope=[],
        definition_of_done=[],
        context=None,
        tdd=None,
        version=1,
        created_at=NOW,
        extras_json=json.dumps(extras) if extras else None,
    )
    tasks_dao.upsert(conn, row)


def test_visual_context_included_in_payload_task(project_dir, conn):
    _make_task(conn, "t-vc-1", visual_context=["/tmp/screen.png", "/tmp/ui.jpg"])
    conn.commit()
    conn.close()

    import os, sys
    os.environ.setdefault("STATE_BACKEND", "sqlite_only")

    from superharness.commands.adapter_payload import build_payload
    payload = build_payload(str(project_dir))

    tasks = payload.get("tasks", [])
    task = next((t for t in tasks if t["id"] == "t-vc-1"), None)
    assert task is not None
    assert task["visual_context"] == ["/tmp/screen.png", "/tmp/ui.jpg"]


def test_visual_context_empty_list_when_absent(project_dir, conn):
    _make_task(conn, "t-vc-2")  # no visual_context
    conn.commit()
    conn.close()

    from superharness.commands.adapter_payload import build_payload
    payload = build_payload(str(project_dir))

    tasks = payload.get("tasks", [])
    task = next((t for t in tasks if t["id"] == "t-vc-2"), None)
    assert task is not None
    assert task["visual_context"] == []


def test_artifacts_key_in_payload(project_dir, conn):
    conn.close()
    from superharness.commands.adapter_payload import build_payload
    payload = build_payload(str(project_dir))
    assert "artifacts" in payload
    assert isinstance(payload["artifacts"], list)


def test_agent_heartbeats_key_in_payload(project_dir, conn):
    conn.close()
    from superharness.commands.adapter_payload import build_payload
    payload = build_payload(str(project_dir))
    assert "agent_heartbeats" in payload
    assert isinstance(payload["agent_heartbeats"], list)
