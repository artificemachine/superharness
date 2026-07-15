"""Iteration 2: issue_url render in `shux contract` and `shux context`."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    from superharness.engine.db import get_connection, init_db

    conn = get_connection(str(project))
    init_db(conn)
    conn.close()
    return project


def _add_task(project: Path, task_id: str, issue_url: str | None = None) -> None:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(project))
    try:
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id=task_id,
            title=f"Task {task_id}",
            owner="claude-code",
            status="todo",
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
            issue_url=issue_url,
        ))
        conn.commit()
    finally:
        conn.close()


def test_contract_shows_issue_url(tmp_path: Path, capsys) -> None:
    from superharness.commands.contract_today import contract_today

    project = _make_project(tmp_path)
    _add_task(project, "t1", issue_url="https://github.com/o/r/issues/9")
    rc = contract_today(str(project))
    assert rc == 0
    out = capsys.readouterr().out
    assert "https://github.com/o/r/issues/9" in out


def test_contract_hides_column_when_absent(tmp_path: Path, capsys) -> None:
    from superharness.commands.contract_today import contract_today

    project = _make_project(tmp_path)
    _add_task(project, "t1")
    rc = contract_today(str(project))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Issue" not in out


def test_contract_render_unchanged_without_issue_url(tmp_path: Path, capsys) -> None:
    """Regression: render output for a project with no linked issues is
    byte-identical to the pre-Iteration-2 4-column table."""
    from superharness.commands.contract_today import contract_today

    project = _make_project(tmp_path)
    _add_task(project, "t1")
    contract_today(str(project))
    out = capsys.readouterr().out
    assert "│ ID" in out
    assert "│ Title" in out
    assert "│ Status" in out
    assert "│ Owner" in out
    assert "Issue" not in out


def test_link_then_render_reflects(tmp_path: Path, capsys) -> None:
    """Integration: create → link → contract shows the URL."""
    from superharness.commands.task import link
    from superharness.commands.contract_today import contract_today

    project = _make_project(tmp_path)
    _add_task(project, "t1")
    link(str(project), "t1", url="https://gitlab.gs/o/r/-/issues/3")
    capsys.readouterr()  # discard link()'s own stdout

    rc = contract_today(str(project))
    assert rc == 0
    out = capsys.readouterr().out
    assert "https://gitlab.gs/o/r/-/issues/3" in out


def test_context_shows_issue_line_when_present(tmp_path: Path) -> None:
    from superharness.commands.context import task_context

    project = _make_project(tmp_path)
    _add_task(project, "t1", issue_url="https://github.com/o/r/issues/9")
    output = task_context(project, "t1")
    assert "Issue: https://github.com/o/r/issues/9" in output


def test_context_omits_issue_line_when_absent(tmp_path: Path) -> None:
    from superharness.commands.context import task_context

    project = _make_project(tmp_path)
    _add_task(project, "t1")
    output = task_context(project, "t1")
    assert "Issue:" not in output
