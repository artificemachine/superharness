"""Tests for `shux task requires` CLI verb — set_requires() function."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _setup_project(tmp_path: Path, owner: str = "claude-code") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow
    from datetime import datetime, timezone

    conn = get_connection(str(project))
    try:
        init_db(conn)
        row = TaskRow(
            id="t-req-test",
            title="Requires test task",
            owner=owner,
            status="plan_approved",
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
        )
        tasks_dao.upsert(conn, row)
        conn.commit()
    finally:
        conn.close()
    return project


def _get_extras(project: Path, task_id: str) -> dict:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    conn = get_connection(str(project))
    try:
        init_db(conn)
        row = tasks_dao.get(conn, task_id)
        assert row is not None
        return json.loads(row.extras_json) if row.extras_json else {}
    finally:
        conn.close()


class TestSetRequiresCLIVerb:
    def test_show_empty_is_zero(self, tmp_path: Path, capsys) -> None:
        from superharness.commands.task import set_requires

        project = _setup_project(tmp_path)
        rc = set_requires(str(project), "t-req-test", show=True)
        assert rc == 0
        out = capsys.readouterr().out
        assert "No requires:" in out

    def test_add_cli_requirement(self, tmp_path: Path) -> None:
        from superharness.commands.task import set_requires

        project = _setup_project(tmp_path)
        rc = set_requires(str(project), "t-req-test", cli_add=["gitleaks"])
        assert rc == 0
        extras = _get_extras(project, "t-req-test")
        req = extras.get("requires", {})
        cli_ids = [i["id"] for i in req.get("cli", [])]
        assert "gitleaks" in cli_ids

    def test_add_multiple_types(self, tmp_path: Path) -> None:
        from superharness.commands.task import set_requires

        project = _setup_project(tmp_path)
        set_requires(str(project), "t-req-test",
                     cli_add=["gitleaks"],
                     env_add=["ALLOW_PUSH"],
                     fail_mode="warn")
        extras = _get_extras(project, "t-req-test")
        req = extras.get("requires", {})
        assert req.get("fail_mode") == "warn"
        assert any(i["id"] == "gitleaks" for i in req.get("cli", []))
        assert any(i["id"] == "ALLOW_PUSH" for i in req.get("env", []))

    def test_remove_cli_requirement(self, tmp_path: Path) -> None:
        from superharness.commands.task import set_requires

        project = _setup_project(tmp_path)
        set_requires(str(project), "t-req-test", cli_add=["gitleaks", "shipguard"])
        set_requires(str(project), "t-req-test", cli_remove=["gitleaks"])
        extras = _get_extras(project, "t-req-test")
        req = extras.get("requires", {})
        cli_ids = [i["id"] for i in req.get("cli", [])]
        assert "gitleaks" not in cli_ids
        assert "shipguard" in cli_ids

    def test_add_is_idempotent(self, tmp_path: Path) -> None:
        from superharness.commands.task import set_requires

        project = _setup_project(tmp_path)
        set_requires(str(project), "t-req-test", cli_add=["gitleaks"])
        set_requires(str(project), "t-req-test", cli_add=["gitleaks"])
        extras = _get_extras(project, "t-req-test")
        req = extras.get("requires", {})
        cli_ids = [i["id"] for i in req.get("cli", [])]
        assert cli_ids.count("gitleaks") == 1

    def test_clear_removes_block(self, tmp_path: Path) -> None:
        from superharness.commands.task import set_requires

        project = _setup_project(tmp_path)
        set_requires(str(project), "t-req-test", cli_add=["gitleaks"])
        set_requires(str(project), "t-req-test", clear=True)
        extras = _get_extras(project, "t-req-test")
        assert "requires" not in extras

    def test_show_populated(self, tmp_path: Path, capsys) -> None:
        from superharness.commands.task import set_requires

        project = _setup_project(tmp_path)
        set_requires(str(project), "t-req-test", cli_add=["gitleaks"], fail_mode="block")
        rc = set_requires(str(project), "t-req-test", show=True)
        assert rc == 0
        out = capsys.readouterr().out
        assert "gitleaks" in out

    def test_unknown_task_returns_nonzero(self, tmp_path: Path) -> None:
        from superharness.commands.task import set_requires

        project = _setup_project(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            set_requires(str(project), "nonexistent-task", cli_add=["gitleaks"])
        assert exc_info.value.code != 0

    def test_requires_persists_across_get_task(self, tmp_path: Path) -> None:
        """set_requires writes to SQLite; state_reader.get_task surfaces it on the task dict."""
        from superharness.commands.task import set_requires
        from superharness.engine import state_reader

        project = _setup_project(tmp_path)
        set_requires(str(project), "t-req-test", cli_add=["gitleaks"])

        tasks = state_reader.get_tasks(str(project))
        task = next((t for t in tasks if t.get("id") == "t-req-test"), None)
        assert task is not None
        req = task.get("requires")
        assert isinstance(req, dict)
        cli_ids = [i["id"] for i in req.get("cli", [])]
        assert "gitleaks" in cli_ids
