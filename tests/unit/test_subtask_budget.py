"""Tests for per-subtask budget tracking and result aggregation."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from superharness.engine.sdk_runner import SDKRunner, BudgetExceededError
from superharness.engine.subtask_aggregator import (
    SubtaskAggregator,
    SubtaskResult,
    aggregate_subtask_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_contract(tmp_path: Path) -> Path:
    harness = tmp_path / ".superharness"
    harness.mkdir()
    contract = {
        "id": "C-001",
        "created": "2026-01-01",
        "created_by": "owner",
        "status": "active",
        "tasks": [
            {
                "id": "T-42",
                "title": "Add rate limiting",
                "owner": "claude-code",
                "status": "in_progress",
                "estimated_cost_usd": 0.30,
                "budget_usd": 0.45,
                "subtasks": [
                    {
                        "id": "T-42.1",
                        "title": "Write middleware",
                        "model_tier": "standard",
                        "owner": "claude-code",
                        "estimated_tokens": 45000,
                        "estimated_cost_usd": 0.28,
                        "status": "pending",
                    },
                    {
                        "id": "T-42.2",
                        "title": "Add Redis backend",
                        "model_tier": "mini",
                        "owner": "claude-code",
                        "estimated_tokens": 12000,
                        "estimated_cost_usd": 0.02,
                        "status": "pending",
                    },
                ],
            }
        ],
    }
    with open(harness / "contract.yaml", "w") as f:
        yaml.safe_dump(contract, f)
    return tmp_path


# ---------------------------------------------------------------------------
# SDKRunner per-subtask budget
# ---------------------------------------------------------------------------


class TestSDKRunnerSubtaskBudget:
    @staticmethod
    def _make_mock_sdk(result_text="OK", input_tokens=10, output_tokens=5):
        """Build a mock_sdk with real class stubs.

        Using real Python classes instead of MagicMock attributes avoids
        ResultMessage.__new__(ResultMessage) failing when the type is a MagicMock.
        """
        import types as _types
        from unittest.mock import MagicMock

        mock_sdk = MagicMock()

        class ClaudeAgentOptions:
            def __init__(self):
                self.model = None
                self.cwd = None
                self.permission_mode = None

        class ResultMessage:
            pass

        class StreamEvent:
            pass

        mock_sdk.ClaudeAgentOptions = ClaudeAgentOptions
        mock_sdk.ResultMessage = ResultMessage
        mock_sdk.StreamEvent = StreamEvent

        evt = ResultMessage()
        evt.result = result_text
        evt.usage = _types.SimpleNamespace(
            input_tokens=input_tokens, output_tokens=output_tokens
        )

        async def _query(*args, **kwargs):
            yield evt

        mock_sdk.query = _query
        return mock_sdk

    def test_subtask_budget_enforced(self, tmp_path):
        """SDKRunner raises BudgetExceededError if subtask budget exceeded."""
        import sys
        mock_sdk = self._make_mock_sdk("ok", 100000, 50000)
        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
                runner = SDKRunner(
                    project_dir=tmp_path,
                    model="claude-sonnet-4-6",
                    max_budget_usd=0.01,
                )
                with pytest.raises(BudgetExceededError):
                    runner.run("expensive subtask")

    def test_subtask_cost_recorded(self, tmp_path):
        """Actual cost per run is accessible after execution."""
        import sys
        mock_sdk = self._make_mock_sdk("ok", 1000, 500)
        with patch("superharness.engine.sdk_runner._try_import_sdk", return_value=True):
            with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
                runner = SDKRunner(
                    project_dir=tmp_path,
                    model="claude-haiku-4-5-20251001",
                )
                result = runner.run("cheap subtask")
        assert result["cost_usd"] > 0
        assert result["input_tokens"] == 1000
        assert result["output_tokens"] == 500


# ---------------------------------------------------------------------------
# SubtaskResult
# ---------------------------------------------------------------------------


class TestSubtaskResult:
    def test_subtask_result_fields(self):
        result = SubtaskResult(
            subtask_id="T-42.1",
            status="done",
            actual_tokens=48000,
            actual_cost_usd=0.31,
            model_used="claude-sonnet-4-6",
            output="Middleware written.",
        )
        assert result.subtask_id == "T-42.1"
        assert result.status == "done"
        assert result.actual_tokens == 48000

    def test_subtask_result_failed(self):
        result = SubtaskResult(
            subtask_id="T-42.2",
            status="failed",
            actual_tokens=0,
            actual_cost_usd=0.0,
            model_used="claude-haiku-4-5-20251001",
            output="",
            error="Budget exceeded",
        )
        assert result.status == "failed"
        assert result.error == "Budget exceeded"


# ---------------------------------------------------------------------------
# SubtaskAggregator
# ---------------------------------------------------------------------------


class TestSubtaskAggregator:
    def test_aggregate_updates_subtask_statuses(self, tmp_path):
        project = _setup_contract(tmp_path)
        contract_file = project / ".superharness" / "contract.yaml"

        results = [
            SubtaskResult("T-42.1", "done", 48000, 0.31, "claude-sonnet-4-6", "OK"),
            SubtaskResult("T-42.2", "done", 11000, 0.019, "claude-haiku-4-5-20251001", "OK"),
        ]

        agg = SubtaskAggregator(str(contract_file))
        agg.record_results("T-42", results)

        with open(contract_file) as f:
            doc = yaml.safe_load(f)
        task = next(t for t in doc["tasks"] if t["id"] == "T-42")
        subtasks = task["subtasks"]

        assert subtasks[0]["status"] == "done"
        assert subtasks[0]["actual_tokens"] == 48000
        assert subtasks[0]["actual_cost_usd"] == pytest.approx(0.31, abs=0.001)
        assert subtasks[0]["model_used"] == "claude-sonnet-4-6"

        assert subtasks[1]["status"] == "done"

    def test_aggregate_computes_total_actual_cost(self, tmp_path):
        project = _setup_contract(tmp_path)
        contract_file = project / ".superharness" / "contract.yaml"

        results = [
            SubtaskResult("T-42.1", "done", 48000, 0.31, "claude-sonnet-4-6", "OK"),
            SubtaskResult("T-42.2", "done", 11000, 0.019, "claude-haiku-4-5-20251001", "OK"),
        ]

        agg = SubtaskAggregator(str(contract_file))
        summary = agg.record_results("T-42", results)

        assert summary.total_actual_cost_usd == pytest.approx(0.329, abs=0.001)
        assert summary.all_done is True
        assert summary.any_failed is False

    def test_aggregate_marks_parent_report_ready_when_all_done(self, tmp_path):
        project = _setup_contract(tmp_path)
        contract_file = project / ".superharness" / "contract.yaml"

        results = [
            SubtaskResult("T-42.1", "done", 48000, 0.31, "claude-sonnet-4-6", "OK"),
            SubtaskResult("T-42.2", "done", 11000, 0.019, "claude-haiku-4-5-20251001", "OK"),
        ]

        agg = SubtaskAggregator(str(contract_file))
        agg.record_results("T-42", results)

        with open(contract_file) as f:
            doc = yaml.safe_load(f)
        task = next(t for t in doc["tasks"] if t["id"] == "T-42")
        assert task["status"] == "report_ready"

    def test_aggregate_marks_parent_failed_when_any_failed(self, tmp_path):
        project = _setup_contract(tmp_path)
        contract_file = project / ".superharness" / "contract.yaml"

        results = [
            SubtaskResult("T-42.1", "done", 48000, 0.31, "claude-sonnet-4-6", "OK"),
            SubtaskResult("T-42.2", "failed", 0, 0.0, "claude-haiku-4-5-20251001", "", error="timeout"),
        ]

        agg = SubtaskAggregator(str(contract_file))
        summary = agg.record_results("T-42", results)

        assert summary.any_failed is True
        assert summary.all_done is False

        with open(contract_file) as f:
            doc = yaml.safe_load(f)
        task = next(t for t in doc["tasks"] if t["id"] == "T-42")
        assert task["status"] == "failed"


# ---------------------------------------------------------------------------
# aggregate_subtask_results convenience function
# ---------------------------------------------------------------------------


class TestSubtaskAggregatorEdgeCases:
    def test_all_done_false_when_no_results_match(self, tmp_path):
        """all_done must not be True when zero results are recorded (regression)."""
        project = _setup_contract(tmp_path)
        contract_file = project / ".superharness" / "contract.yaml"

        agg = SubtaskAggregator(str(contract_file))
        summary = agg.record_results("T-42", [])

        assert summary.all_done is False
        assert summary.any_failed is False

        with open(contract_file) as f:
            doc = yaml.safe_load(f)
        task = next(t for t in doc["tasks"] if t["id"] == "T-42")
        assert task["status"] == "in_progress"  # unchanged, not promoted

    def test_all_done_false_when_partial_results(self, tmp_path):
        """all_done False when only one of two subtasks has a result."""
        project = _setup_contract(tmp_path)
        contract_file = project / ".superharness" / "contract.yaml"

        results = [
            SubtaskResult("T-42.1", "done", 48000, 0.31, "claude-sonnet-4-6", "OK"),
            # T-42.2 has no result
        ]

        agg = SubtaskAggregator(str(contract_file))
        summary = agg.record_results("T-42", results)

        assert summary.all_done is False

        with open(contract_file) as f:
            doc = yaml.safe_load(f)
        task = next(t for t in doc["tasks"] if t["id"] == "T-42")
        assert task["status"] == "in_progress"  # not promoted


class TestAggregateSubtaskResults:
    def test_convenience_function(self, tmp_path):
        project = _setup_contract(tmp_path)
        contract_file = str(project / ".superharness" / "contract.yaml")

        results = [
            SubtaskResult("T-42.1", "done", 48000, 0.31, "claude-sonnet-4-6", "OK"),
            SubtaskResult("T-42.2", "done", 11000, 0.019, "claude-haiku-4-5-20251001", "OK"),
        ]

        summary = aggregate_subtask_results(contract_file, "T-42", results)
        assert summary.all_done is True
        assert summary.total_actual_cost_usd > 0
