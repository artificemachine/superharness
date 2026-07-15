"""Iteration 4: close-time drift nudge for tasks with a linked issue_url."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest


def _seed_report_ready_task(project: Path, issue_url: str | None = None) -> None:
    (project / ".superharness" / "handoffs").mkdir(parents=True, exist_ok=True)
    from superharness.engine.db import get_connection, init_db, transaction
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(project))
    init_db(conn)
    with transaction(conn):
        tasks_dao.upsert(conn, TaskRow(
            id="feat-001",
            title="Build feature one",
            owner="claude-code",
            status="report_ready",
            effort="medium",
            project_path=str(project),
            development_method="tdd",
            acceptance_criteria=[],
            test_types=[],
            out_of_scope=[],
            definition_of_done=[],
            context=None,
            tdd=None,
            version=1,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            verified=True,
            verified_at="2026-03-15T00:00:00Z",
            verified_by="claude-code",
            issue_url=issue_url,
        ))
    conn.commit()
    conn.close()


def test_close_prints_nudge_when_issue_url_set(tmp_path: Path, capsys) -> None:
    from superharness.commands import close as close_mod

    project = tmp_path / "proj"
    _seed_report_ready_task(project, issue_url="https://github.com/o/r/issues/9")

    rc = close_mod.close_task(
        project_dir=str(project), task_id="feat-001",
        actor="claude-code", summary="done",
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "https://github.com/o/r/issues/9" in out
    assert "gh issue close" in out


def test_close_no_nudge_when_no_issue_url(tmp_path: Path, capsys) -> None:
    from superharness.commands import close as close_mod

    project = tmp_path / "proj"
    _seed_report_ready_task(project)

    rc = close_mod.close_task(
        project_dir=str(project), task_id="feat-001",
        actor="claude-code", summary="done",
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Linked issue" not in out
    assert "issue close" not in out


def test_close_output_unchanged_without_issue_url(tmp_path: Path, capsys) -> None:
    """Regression: close output for a task with no issue_url is unchanged."""
    from superharness.commands import close as close_mod

    project = tmp_path / "proj"
    _seed_report_ready_task(project)

    close_mod.close_task(
        project_dir=str(project), task_id="feat-001",
        actor="claude-code", summary="done",
    )
    out = capsys.readouterr().out
    assert out == "Closed task 'feat-001' (actor=claude-code)\n"


@pytest.mark.parametrize("url,expected_bin", [
    ("https://github.com/o/r/issues/9", "gh"),
    ("https://gitlab.gs/o/r/-/issues/3", "glab"),
])
def test_nudge_command_matches_platform(tmp_path: Path, capsys, url, expected_bin) -> None:
    from superharness.commands import close as close_mod

    project = tmp_path / "proj"
    _seed_report_ready_task(project, issue_url=url)

    close_mod.close_task(
        project_dir=str(project), task_id="feat-001",
        actor="claude-code", summary="done",
    )
    out = capsys.readouterr().out
    assert f"{expected_bin} issue close {url}" in out


def test_close_command_runs_with_linked_task(tmp_path: Path) -> None:
    """Smoke: the close path executes end-to-end on a task carrying issue_url."""
    from superharness.commands import close as close_mod

    project = tmp_path / "proj"
    _seed_report_ready_task(project, issue_url="https://github.com/o/r/issues/9")

    rc = close_mod.close_task(
        project_dir=str(project), task_id="feat-001",
        actor="claude-code", summary="done",
    )
    assert rc == 0
