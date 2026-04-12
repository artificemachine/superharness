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
# write_subtasks_to_contract
# ---------------------------------------------------------------------------


class TestWriteSubtasksToContract:
    def test_subtasks_written_to_contract(self, tmp_path):
        from superharness.commands.delegate import _write_subtasks_to_contract

        project = _setup_project(tmp_path)
        contract_file = project / ".superharness" / "contract.yaml"

        _write_subtasks_to_contract(
            str(contract_file), "T-42", MOCK_DECOMPOSITION
        )

        with open(contract_file) as f:
            doc = yaml.safe_load(f)

        task = next(t for t in doc["tasks"] if t["id"] == "T-42")
        assert "subtasks" in task
        assert len(task["subtasks"]) == 2
        assert task["subtasks"][0]["id"] == "T-42.1"
        assert task["subtasks"][1]["id"] == "T-42.2"

    def test_cost_fields_written(self, tmp_path):
        from superharness.commands.delegate import _write_subtasks_to_contract

        project = _setup_project(tmp_path)
        contract_file = project / ".superharness" / "contract.yaml"

        _write_subtasks_to_contract(
            str(contract_file), "T-42", MOCK_DECOMPOSITION
        )

        with open(contract_file) as f:
            doc = yaml.safe_load(f)

        task = next(t for t in doc["tasks"] if t["id"] == "T-42")
        assert task["estimated_cost_usd"] == pytest.approx(0.30, abs=0.01)
        assert task["budget_usd"] == pytest.approx(0.45, abs=0.01)

    def test_subtask_tiers_preserved(self, tmp_path):
        from superharness.commands.delegate import _write_subtasks_to_contract

        project = _setup_project(tmp_path)
        contract_file = project / ".superharness" / "contract.yaml"

        _write_subtasks_to_contract(
            str(contract_file), "T-42", MOCK_DECOMPOSITION
        )

        with open(contract_file) as f:
            doc = yaml.safe_load(f)

        task = next(t for t in doc["tasks"] if t["id"] == "T-42")
        tiers = [st["model_tier"] for st in task["subtasks"]]
        assert tiers == ["standard", "mini"]


# ---------------------------------------------------------------------------
# Orchestrate mode in delegate
# ---------------------------------------------------------------------------


class TestOrchestrateMode:
    def test_orchestrate_flag_triggers_decomposition(self, tmp_path):
        """--orchestrate causes delegate to decompose before dispatch."""
        from superharness.commands.delegate import delegate

        project = _setup_project(tmp_path)

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

        project = _setup_project(tmp_path)

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

        project = _setup_project(tmp_path)

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
