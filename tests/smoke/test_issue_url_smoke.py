"""Smoke test for issue_url — schema column presence and create() persistence."""
from __future__ import annotations

from superharness.engine.db import get_connection, init_db


def test_issue_url_column_exists_after_init(tmp_path):
    (tmp_path / ".superharness").mkdir()
    conn = get_connection(str(tmp_path))
    init_db(conn)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    conn.close()
    assert "issue_url" in columns


def test_create_with_issue_flag_persists(tmp_path):
    from superharness.commands.task import create
    from superharness.engine import tasks_dao

    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True)

    rc = create(
        project_dir=str(project),
        task_id="t-issue",
        title="Task with issue",
        owner="claude-code",
        status="todo",
        project_path=str(project),
        issue_url="https://github.com/o/r/issues/1",
    )
    assert rc == 0

    conn = get_connection(str(project))
    init_db(conn)
    row = tasks_dao.get(conn, "t-issue")
    conn.close()
    assert row.issue_url == "https://github.com/o/r/issues/1"
