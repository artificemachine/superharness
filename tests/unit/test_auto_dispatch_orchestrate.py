"""Tests for run_auto_dispatch --orchestrate: parallel subtask fan-out.

Plan: PLAN-superharness-parallel-dispatch.md
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_project(tmp_path: Path, effort: str = "high", status: str = "todo") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    conn = get_connection(str(project))
    try:
        init_db(conn)
        row = TaskRow(
            id="t-orch-test",
            title="High effort orchestrate test",
            owner="claude-code",
            status=status,
            effort=effort,
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


def _make_decomposition(parent_id: str, n: int = 2):
    from superharness.engine.orchestrator import DecompositionResult
    subtasks = [
        {
            "id": f"{parent_id}.st{i + 1}",
            "title": f"Subtask {i + 1}",
            "owner": "claude-code",
            "effort": "medium",
            "model_tier": "standard",
            "estimated_tokens": 10000,
        }
        for i in range(n)
    ]
    return DecompositionResult(subtasks=subtasks)


def _get_tasks(project: Path) -> list[dict]:
    from superharness.engine import state_reader
    return state_reader.get_tasks(str(project))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOrchestrateDecomposesHighEffortTask:
    def test_subtasks_registered_in_sqlite(self, tmp_path):
        """With --orchestrate, high-effort todo task is decomposed into subtasks in SQLite."""
        project = _setup_project(tmp_path, effort="high")
        fake = _make_decomposition("t-orch-test", n=2)

        with patch("superharness.commands.auto_dispatch.Orchestrator") as Mock:
            Mock.return_value.decompose.return_value = fake
            from superharness.commands.auto_dispatch import run_auto_dispatch
            rc = run_auto_dispatch(str(project), orchestrate=True, effort_gate="high")

        assert rc == 0
        tasks = _get_tasks(project)
        subtask_ids = [t["id"] for t in tasks if t.get("id", "").startswith("t-orch-test.st")]
        assert len(subtask_ids) == 2

    def test_parent_task_becomes_in_progress(self, tmp_path):
        """After decomposition parent task status is in_progress."""
        project = _setup_project(tmp_path, effort="high")
        fake = _make_decomposition("t-orch-test", n=2)

        with patch("superharness.commands.auto_dispatch.Orchestrator") as Mock:
            Mock.return_value.decompose.return_value = fake
            from superharness.commands.auto_dispatch import run_auto_dispatch
            run_auto_dispatch(str(project), orchestrate=True, effort_gate="high")

        tasks = _get_tasks(project)
        parent = next((t for t in tasks if t["id"] == "t-orch-test"), None)
        assert parent is not None
        assert parent["status"] == "in_progress"

    def test_orchestrate_false_does_not_decompose(self, tmp_path):
        """Without --orchestrate, high-effort tasks are enqueued normally (no decomposition)."""
        project = _setup_project(tmp_path, effort="high")

        with patch("superharness.commands.auto_dispatch.Orchestrator") as Mock:
            from superharness.commands.auto_dispatch import run_auto_dispatch
            run_auto_dispatch(str(project), orchestrate=False, effort_gate="high")
            Mock.return_value.decompose.assert_not_called()

        tasks = _get_tasks(project)
        subtasks = [t for t in tasks if ".st" in t.get("id", "")]
        assert len(subtasks) == 0


class TestOrchestrateLowEffortSkipped:
    def test_low_effort_not_decomposed(self, tmp_path):
        """low effort is below the 'high' gate — Orchestrator.decompose not called."""
        project = _setup_project(tmp_path, effort="low")

        with patch("superharness.commands.auto_dispatch.Orchestrator") as Mock:
            from superharness.commands.auto_dispatch import run_auto_dispatch
            run_auto_dispatch(str(project), orchestrate=True, effort_gate="high")
            Mock.return_value.decompose.assert_not_called()

    def test_medium_effort_not_decomposed_at_high_gate(self, tmp_path):
        """medium effort is below the 'high' gate — no decomposition."""
        project = _setup_project(tmp_path, effort="medium")

        with patch("superharness.commands.auto_dispatch.Orchestrator") as Mock:
            from superharness.commands.auto_dispatch import run_auto_dispatch
            run_auto_dispatch(str(project), orchestrate=True, effort_gate="high")
            Mock.return_value.decompose.assert_not_called()


class TestDryRunWithOrchestrate:
    def test_dry_run_prints_orchestrate_note(self, tmp_path, capsys):
        """--dry-run --orchestrate prints decomposition plan without writing SQLite."""
        project = _setup_project(tmp_path, effort="high")
        fake = _make_decomposition("t-orch-test", n=3)

        with patch("superharness.commands.auto_dispatch.Orchestrator") as Mock:
            Mock.return_value.decompose.return_value = fake
            from superharness.commands.auto_dispatch import run_auto_dispatch
            rc = run_auto_dispatch(str(project), orchestrate=True, dry_run=True, effort_gate="high")

        assert rc == 0
        out = capsys.readouterr().out
        assert any(kw in out.lower() for kw in ("decompose", "orchestrate", "subtask", "orch"))

    def test_dry_run_writes_no_subtasks(self, tmp_path):
        """--dry-run leaves SQLite unchanged — no subtasks created."""
        project = _setup_project(tmp_path, effort="high")
        fake = _make_decomposition("t-orch-test", n=2)

        with patch("superharness.commands.auto_dispatch.Orchestrator") as Mock:
            Mock.return_value.decompose.return_value = fake
            from superharness.commands.auto_dispatch import run_auto_dispatch
            run_auto_dispatch(str(project), orchestrate=True, dry_run=True, effort_gate="high")

        tasks = _get_tasks(project)
        subtasks = [t for t in tasks if t.get("id", "").startswith("t-orch-test.st")]
        assert len(subtasks) == 0


class TestOrchestrateEmptyDecompositionFallback:
    def test_empty_subtasks_falls_back_to_normal_enqueue(self, tmp_path):
        """If Orchestrator returns 0 subtasks, original task is enqueued normally (no silent drop)."""
        from superharness.engine.orchestrator import DecompositionResult
        project = _setup_project(tmp_path, effort="high")
        empty = DecompositionResult(subtasks=[])

        with patch("superharness.commands.auto_dispatch.Orchestrator") as Mock:
            Mock.return_value.decompose.return_value = empty
            from superharness.commands.auto_dispatch import run_auto_dispatch
            rc = run_auto_dispatch(str(project), orchestrate=True, effort_gate="high")

        assert rc == 0
        from superharness.engine import inbox_dao
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(str(project))
        try:
            init_db(conn)
            items = inbox_dao.get_all(conn)
        finally:
            conn.close()
        enqueued_ids = [i.task_id for i in items]
        assert "t-orch-test" in enqueued_ids
