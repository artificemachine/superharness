"""Phase 2+3 YAML cleanup tests.

Phase 2: inbox_watch.py — no contract.yaml/inbox.yaml reads
Phase 3: adapter_payload.py — no YAML fallbacks in _load_failures/decisions/inbox;
         validate.py / doctor.py — check state.sqlite3 not contract.yaml
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine import tasks_dao
from superharness.engine.tasks_dao import TaskRow

T0 = "2026-01-01T00:00:00Z"


def _mk_project(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    p.mkdir()
    (p / ".superharness").mkdir()
    conn = get_connection(str(p))
    init_db(conn)
    conn.commit()
    conn.close()
    return p


# ---------------------------------------------------------------------------
# Phase 2: inbox_watch._ensure_task_in_sqlite — no YAML read
# ---------------------------------------------------------------------------

class TestEnsureTaskInSqliteNoYaml:
    def test_returns_without_reading_yaml_when_no_db(self, tmp_path: Path) -> None:
        """_ensure_task_in_sqlite must not crash when called on a project
        that has no contract.yaml — it should just return silently."""
        project = _mk_project(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)
        # No contract.yaml — should not raise
        from superharness.commands.inbox_watch import _ensure_task_in_sqlite
        _ensure_task_in_sqlite(conn, "t-missing", str(project), T0)
        # Task should not be created (no seed source)
        task = tasks_dao.get(conn, "t-missing")
        assert task is None
        conn.close()

    def test_no_op_when_task_exists(self, tmp_path: Path) -> None:
        project = _mk_project(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)
        tasks_dao.upsert(conn, TaskRow(
            id="t1", title="T", owner="x", status="todo", effort=None,
            project_path=str(project), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[],
            definition_of_done=[], context=None, tdd=None, version=1, created_at=T0,
        ))
        conn.commit()
        from superharness.commands.inbox_watch import _ensure_task_in_sqlite
        _ensure_task_in_sqlite(conn, "t1", str(project), T0)
        # Should not raise; task still present
        assert tasks_dao.get(conn, "t1") is not None
        conn.close()


# ---------------------------------------------------------------------------
# Phase 3: adapter_payload._load_failures — no YAML fallback
# ---------------------------------------------------------------------------

class TestLoadFailuresNoYaml:
    def test_returns_empty_when_no_db_no_yaml(self, tmp_path: Path) -> None:
        project = _mk_project(tmp_path)
        from superharness.commands.adapter_payload import _load_failures
        result = _load_failures(project / ".superharness")
        assert result == []

    def test_yaml_file_not_read_when_sqlite_has_no_rows(self, tmp_path: Path) -> None:
        project = _mk_project(tmp_path)
        # Write a failures.yaml with stale data
        (project / ".superharness" / "failures.yaml").write_text(
            "failures:\n- task: old\n  error_snippet: stale\n  agent: x\n  date: 2020-01-01\n"
        )
        from superharness.commands.adapter_payload import _load_failures
        result = _load_failures(project / ".superharness")
        # Should NOT return the YAML data (fallback removed)
        assert result == []


# ---------------------------------------------------------------------------
# Phase 3: adapter_payload._load_decisions — no YAML fallback
# ---------------------------------------------------------------------------

class TestLoadDecisionsNoYaml:
    def test_returns_empty_when_sqlite_empty(self, tmp_path: Path) -> None:
        project = _mk_project(tmp_path)
        from superharness.commands.adapter_payload import _load_decisions
        result = _load_decisions(project / ".superharness")
        assert result == []

    def test_yaml_not_read_as_fallback(self, tmp_path: Path) -> None:
        project = _mk_project(tmp_path)
        (project / ".superharness" / "decisions.yaml").write_text(
            "decisions:\n- id: d1\n  what: old decision\n  why: stale\n"
        )
        from superharness.commands.adapter_payload import _load_decisions
        result = _load_decisions(project / ".superharness")
        assert result == []


# ---------------------------------------------------------------------------
# Phase 3: adapter_payload._load_inbox — no YAML fallback
# ---------------------------------------------------------------------------

class TestLoadInboxNoYaml:
    def test_returns_empty_when_sqlite_empty(self, tmp_path: Path) -> None:
        project = _mk_project(tmp_path)
        from superharness.commands.adapter_payload import _load_inbox
        result = _load_inbox(project / ".superharness")
        assert result == []

    def test_yaml_not_read_as_fallback(self, tmp_path: Path) -> None:
        project = _mk_project(tmp_path)
        (project / ".superharness" / "inbox.yaml").write_text(
            "[{id: i1, task: t1, status: pending, to: claude-code}]\n"
        )
        from superharness.commands.adapter_payload import _load_inbox
        result = _load_inbox(project / ".superharness")
        assert result == []


# ---------------------------------------------------------------------------
# Phase 3: validate.py — checks state.sqlite3 not contract.yaml
# ---------------------------------------------------------------------------

class TestValidateChecksDb:
    def test_missing_sqlite_returns_nonzero(self, tmp_path: Path) -> None:
        """run_validate must fail when state.sqlite3 is absent."""
        project = tmp_path / "proj"
        (project / ".superharness").mkdir(parents=True)
        (project / ".superharness" / "handoffs").mkdir()
        (project / ".superharness" / "ledger.md").write_text("")
        # No state.sqlite3 — should return non-zero
        from superharness.engine.validate import run_validate
        result = run_validate(str(project))
        assert result != 0

    def test_sqlite_present_passes_required_check(self, tmp_path: Path) -> None:
        """run_validate should not fail the required-path check when sqlite exists."""
        project = _mk_project(tmp_path)
        (project / ".superharness" / "handoffs").mkdir()
        (project / ".superharness" / "ledger.md").write_text("")
        from superharness.engine.validate import run_validate
        result = run_validate(str(project))
        assert result == 0
