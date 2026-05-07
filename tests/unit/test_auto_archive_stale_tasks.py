"""Regression tests for _auto_archive_stale_tasks().

Bug: a plan-phase handoff (e.g. task-plan-2026-05-06-agent.yaml) blocked
auto-archive of tasks stuck in_progress with a failed agent. Only report-phase
handoffs should exempt a task from auto-archive.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    (project / ".superharness" / "handoffs").mkdir()
    return project


def _insert_task(project: Path, task_id: str, status: str, hours_ago: float) -> None:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    in_progress_at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    conn = get_connection(str(project))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, tasks_dao.TaskRow(
            id=task_id,
            title=task_id,
            owner="claude-code",
            status=status,
            effort=None,
            project_path=str(project),
            development_method=None,
            acceptance_criteria=[],
            test_types=[],
            out_of_scope=[],
            definition_of_done=[],
            context=None,
            tdd=None,
            version=1,
            created_at=in_progress_at,
            in_progress_at=in_progress_at,
        ))
        conn.commit()
    finally:
        conn.close()


def _write_handoff(project: Path, filename: str) -> None:
    path = project / ".superharness" / "handoffs" / filename
    path.write_text("phase: plan\n")


def _get_task_status(project: Path, task_id: str) -> str:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    conn = get_connection(str(project))
    try:
        init_db(conn)
        for t in tasks_dao.get_all(conn):
            if t.id == task_id:
                return t.status
    finally:
        conn.close()
    return ""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_plan_handoff_does_not_block_archive(tmp_path):
    """Task with only a plan-phase handoff must be auto-archived when stale."""
    from superharness.commands.inbox_watch import _auto_archive_stale_tasks

    project = _setup_project(tmp_path)
    _insert_task(project, "stuck-task", "in_progress", hours_ago=5.0)
    _write_handoff(project, "stuck-task-plan-2026-05-06-agent.yaml")

    archived = _auto_archive_stale_tasks(str(project))

    assert archived == 1
    assert _get_task_status(project, "stuck-task") == "archived"


def test_report_handoff_blocks_archive(tmp_path):
    """Task with a report-phase handoff must NOT be auto-archived."""
    from superharness.commands.inbox_watch import _auto_archive_stale_tasks

    project = _setup_project(tmp_path)
    _insert_task(project, "done-task", "in_progress", hours_ago=5.0)
    _write_handoff(project, "done-task-report-2026-05-06-agent.yaml")

    archived = _auto_archive_stale_tasks(str(project))

    assert archived == 0
    assert _get_task_status(project, "done-task") == "in_progress"


def test_no_handoff_archives_stale_task(tmp_path):
    """Task with no handoff at all must be auto-archived when stale."""
    from superharness.commands.inbox_watch import _auto_archive_stale_tasks

    project = _setup_project(tmp_path)
    _insert_task(project, "ghost-task", "in_progress", hours_ago=6.0)

    archived = _auto_archive_stale_tasks(str(project))

    assert archived == 1
    assert _get_task_status(project, "ghost-task") == "archived"


def test_fresh_task_not_archived(tmp_path):
    """Task in_progress for less than 4h must not be archived."""
    from superharness.commands.inbox_watch import _auto_archive_stale_tasks

    project = _setup_project(tmp_path)
    _insert_task(project, "fresh-task", "in_progress", hours_ago=1.0)

    archived = _auto_archive_stale_tasks(str(project))

    assert archived == 0
    assert _get_task_status(project, "fresh-task") == "in_progress"


def test_done_handoff_filename_blocks_archive(tmp_path):
    """A handoff named with '-done-' in the filename also blocks archive."""
    from superharness.commands.inbox_watch import _auto_archive_stale_tasks

    project = _setup_project(tmp_path)
    _insert_task(project, "closed-task", "in_progress", hours_ago=5.0)
    _write_handoff(project, "closed-task-done-2026-05-06-agent.yaml")

    archived = _auto_archive_stale_tasks(str(project))

    assert archived == 0
