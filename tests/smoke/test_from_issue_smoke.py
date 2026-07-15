"""Iteration 3: `shux task create --from-issue` smoke + create-path regression."""
from __future__ import annotations

from pathlib import Path

import pytest


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    from superharness.engine.db import get_connection, init_db

    conn = get_connection(str(project))
    init_db(conn)
    conn.close()
    return project


def test_from_issue_prefills_task(tmp_path: Path, monkeypatch) -> None:
    from superharness.commands import task as task_mod
    from superharness.engine import tasks_dao
    from superharness.engine.db import get_connection, init_db

    project = _make_project(tmp_path)

    fixture_issue = {
        "title": "Fix the thing",
        "body": "Context.\n- [ ] step one",
        "labels": [{"name": "bug"}],
    }
    monkeypatch.setattr(
        "superharness.commands.issue_import._fetch_issue",
        lambda url: fixture_issue,
    )

    with pytest.raises(SystemExit) as exc_info:
        task_mod.main([
            "create",
            "--project", str(project),
            "--from-issue", "https://github.com/o/r/issues/5",
            "--owner", "claude-code",
        ])
    assert exc_info.value.code == 0

    conn = get_connection(str(project))
    init_db(conn)
    tasks = tasks_dao.get_all(conn)
    conn.close()
    assert len(tasks) == 1
    task = tasks[0]
    assert task.title == "Fix the thing"
    assert task.context == "Context.\n- [ ] step one"
    assert task.acceptance_criteria == ["step one"]
    assert task.issue_url == "https://github.com/o/r/issues/5"


def test_from_issue_explicit_flags_override(tmp_path: Path, monkeypatch) -> None:
    from superharness.commands import task as task_mod
    from superharness.engine import tasks_dao
    from superharness.engine.db import get_connection, init_db

    project = _make_project(tmp_path)

    fixture_issue = {"title": "Imported title", "body": "imported body", "labels": []}
    monkeypatch.setattr(
        "superharness.commands.issue_import._fetch_issue",
        lambda url: fixture_issue,
    )

    with pytest.raises(SystemExit) as exc_info:
        task_mod.main([
            "create",
            "--project", str(project),
            "--from-issue", "https://github.com/o/r/issues/5",
            "--owner", "claude-code",
            "--title", "Explicit title",
        ])
    assert exc_info.value.code == 0

    conn = get_connection(str(project))
    init_db(conn)
    tasks = tasks_dao.get_all(conn)
    conn.close()
    assert tasks[0].title == "Explicit title"


def test_create_without_from_issue_unchanged(tmp_path: Path) -> None:
    """Regression: normal create path (no --from-issue) is unaffected."""
    from superharness.commands import task as task_mod
    from superharness.engine import tasks_dao
    from superharness.engine.db import get_connection, init_db

    project = _make_project(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        task_mod.main([
            "create",
            "--project", str(project),
            "--title", "Normal task",
            "--owner", "claude-code",
        ])
    assert exc_info.value.code == 0

    conn = get_connection(str(project))
    init_db(conn)
    tasks = tasks_dao.get_all(conn)
    conn.close()
    assert len(tasks) == 1
    assert tasks[0].title == "Normal task"
    assert tasks[0].issue_url is None


def test_create_without_title_or_from_issue_errors(tmp_path: Path) -> None:
    """Regression: --title is still required when --from-issue is absent."""
    from superharness.commands import task as task_mod

    project = _make_project(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        task_mod.main([
            "create",
            "--project", str(project),
            "--owner", "claude-code",
        ])
    assert exc_info.value.code != 0
