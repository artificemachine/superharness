"""Tests for orchestrator mode in delegate command.

When --orchestrate is passed, delegate uses Opus to decompose the task,
then writes subtasks to contract.yaml and dispatches sub-agents.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from superharness.engine.orchestrator import Orchestrator, DecompositionResult
from superharness.engine.cost_estimator import CostEstimate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_project(tmp_path: Path) -> Path:
    """Create a minimal .superharness project structure."""
    harness = tmp_path / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()

    contract = {
        "id": "C-001",
        "created": "2026-01-01",
        "created_by": "owner",
        "status": "active",
        "tasks": [
            {
                "id": "T-42",
                "title": "Add rate limiting to API",
                "owner": "claude-code",
                "status": "plan_approved",
                "project_path": str(tmp_path),
                "acceptance_criteria": [
                    "Rate limiter rejects >100 req/min per IP",
                    "Redis backend for counters",
                ],
            }
        ],
    }
    with open(harness / "contract.yaml", "w") as f:
        yaml.safe_dump(contract, f)

    profile = {
        "project_name": "test",
        "created": "2026-01-01",
        "autonomy": "autonomous",
        "primary_agent": "claude-code",
        "stack": "python",
    }
    with open(harness / "profile.yaml", "w") as f:
        yaml.safe_dump(profile, f)

    (harness / "ledger.md").write_text("# Ledger\n")

    return tmp_path


MOCK_DECOMPOSITION = DecompositionResult(
    subtasks=[
        {
            "id": "T-42.1",
            "title": "Write rate limiter middleware",
            "model_tier": "standard",
            "owner": "claude-code",
            "estimated_tokens": 45000,
            "estimated_cost_usd": 0.28,
            "rationale": "Multi-file coding",
        },
        {
            "id": "T-42.2",
            "title": "Add Redis backend",
            "model_tier": "mini",
            "owner": "claude-code",
            "estimated_tokens": 12000,
            "estimated_cost_usd": 0.02,
            "rationale": "Boilerplate",
        },
    ],
    cost_breakdown=[
        CostEstimate(
            model_id="claude-sonnet-4-6",
            tier="standard",
            estimated_input_tokens=27000,
            estimated_output_tokens=18000,
            estimated_cost_usd=0.28,
        ),
        CostEstimate(
            model_id="claude-haiku-4-5-20251001",
            tier="mini",
            estimated_input_tokens=7200,
            estimated_output_tokens=4800,
            estimated_cost_usd=0.02,
        ),
    ],
    total_estimated_cost_usd=0.30,
    recommended_budget_usd=0.45,
)


# ---------------------------------------------------------------------------
# _record_decomposition
# ---------------------------------------------------------------------------


class TestRecordDecomposition:
    def test_subtasks_written_to_sqlite(self, tmp_path):
        from superharness.commands.delegate import _record_decomposition
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        from tests.helpers import seed_sqlite_from_yaml

        project = _setup_project(tmp_path)
        seed_sqlite_from_yaml(project)

        _record_decomposition(str(project), "T-42", MOCK_DECOMPOSITION)

        conn = get_connection(str(project))
        try:
            init_db(conn)
            # 1. Verify separate rows
            row1 = tasks_dao.get(conn, "T-42.1")
            row2 = tasks_dao.get(conn, "T-42.2")
            assert row1.title == "Write rate limiter middleware"
            assert row1.parent_id == "T-42"
            assert row2.title == "Add Redis backend"
            assert row2.parent_id == "T-42"

            # 2. Verify parent extras_json
            parent = tasks_dao.get(conn, "T-42")
            import json
            extras = json.loads(parent.extras_json)
            assert "subtasks" in extras
            assert len(extras["subtasks"]) == 2
            assert extras["budget_usd"] == pytest.approx(0.45, abs=0.01)
        finally:
            conn.close()

    def test_cost_fields_persisted(self, tmp_path):
        from superharness.commands.delegate import _record_decomposition
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        from tests.helpers import seed_sqlite_from_yaml

        project = _setup_project(tmp_path)
        seed_sqlite_from_yaml(project)

        _record_decomposition(str(project), "T-42", MOCK_DECOMPOSITION)

        conn = get_connection(str(project))
        try:
            init_db(conn)
            parent = tasks_dao.get(conn, "T-42")
            import json
            extras = json.loads(parent.extras_json)
            assert extras["estimated_cost_usd"] == pytest.approx(0.30, abs=0.01)
            assert extras["budget_usd"] == pytest.approx(0.45, abs=0.01)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Orchestrate mode in delegate
# ---------------------------------------------------------------------------


class TestOrchestrateMode:
    def test_orchestrate_flag_triggers_decomposition(self, tmp_path):
        """--orchestrate causes delegate to decompose before dispatch."""
        from superharness.commands.delegate import delegate
        from tests.helpers import seed_sqlite_from_yaml

        project = _setup_project(tmp_path)
        seed_sqlite_from_yaml(project)

        with patch("superharness.commands.delegate.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.decompose.return_value = MOCK_DECOMPOSITION

            with patch("superharness.commands.delegate._launch_agent"):
                with patch("superharness.commands.delegate.sdk_available", return_value=False):
                    rc = delegate(
                        project_dir=str(project),
                        target="claude-code",
                        task_id="T-42",
                        print_only=True,
                        non_interactive=False,
                        codex_bypass=False,
                        orchestrate=True,
                        no_auto_model=True,
                    )

            mock_instance.decompose.assert_called_once()
            assert rc == 0

    def test_orchestrate_prints_cost_summary(self, tmp_path, capsys):
        """--orchestrate prints decomposition and cost before dispatch."""
        from superharness.commands.delegate import delegate
        from tests.helpers import seed_sqlite_from_yaml

        project = _setup_project(tmp_path)
        seed_sqlite_from_yaml(project)

        with patch("superharness.commands.delegate.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.decompose.return_value = MOCK_DECOMPOSITION

            with patch("superharness.commands.delegate._launch_agent"):
                with patch("superharness.commands.delegate.sdk_available", return_value=False):
                    delegate(
                        project_dir=str(project),
                        target="claude-code",
                        task_id="T-42",
                        print_only=True,
                        non_interactive=False,
                        codex_bypass=False,
                        orchestrate=True,
                        no_auto_model=True,
                    )

        captured = capsys.readouterr()
        assert "T-42.1" in captured.out
        assert "T-42.2" in captured.out

    def test_orchestrate_works_for_codex_cli(self, tmp_path):
        """--orchestrate now works for codex-cli, not just claude-code."""
        from superharness.commands.delegate import delegate
        from tests.helpers import seed_sqlite_from_yaml

        project = _setup_project(tmp_path)
        seed_sqlite_from_yaml(project)

        with patch("superharness.commands.delegate.Orchestrator") as MockOrch:
            mock_instance = MockOrch.return_value
            mock_instance.decompose.return_value = MOCK_DECOMPOSITION

            with patch("superharness.commands.delegate._launch_agent"):
                with patch("superharness.commands.delegate.sdk_available", return_value=False):
                    rc = delegate(
                        project_dir=str(project),
                        target="codex-cli",
                        task_id="T-42",
                        print_only=True,
                        non_interactive=False,
                        codex_bypass=False,
                        orchestrate=True,
                        no_auto_model=True,
                    )

        mock_instance.decompose.assert_called_once()
        # owner in task_data should reflect the actual target
        call_args = mock_instance.decompose.call_args[0][0]
        assert call_args["owner"] == "codex-cli"
        assert rc == 0
