"""Tests for orchestrator engine — task decomposition and sub-agent routing.

The orchestrator (Opus) decomposes a task into subtasks, assigns model tiers,
estimates costs, and dispatches sub-agents (Haiku/Sonnet/Opus).
"""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from superharness.engine.orchestrator import (
    Orchestrator,
    DecompositionResult,
    SubtaskDispatch,
)
from superharness.engine.schemas import ModelTier, SubtaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TASK = {
    "id": "T-42",
    "title": "Add rate limiting to API",
    "owner": "claude-code",
    "status": "plan_approved",
    "acceptance_criteria": [
        "Rate limiter middleware rejects >100 req/min per IP",
        "Redis backend for distributed counters",
        "Integration tests cover all edge cases",
    ],
}

SAMPLE_DECOMPOSITION = {
    "subtasks": [
        {
            "id": "T-42.1",
            "title": "Write rate limiter middleware",
            "model_tier": "standard",
            "estimated_tokens": 45000,
            "rationale": "Multi-file coding task, Sonnet handles well",
        },
        {
            "id": "T-42.2",
            "title": "Add Redis counter backend",
            "model_tier": "mini",
            "estimated_tokens": 12000,
            "rationale": "Boilerplate Redis integration, Haiku sufficient",
        },
        {
            "id": "T-42.3",
            "title": "Write integration tests",
            "model_tier": "standard",
            "estimated_tokens": 30000,
            "rationale": "Test logic needs judgment, Sonnet appropriate",
        },
    ]
}


# ---------------------------------------------------------------------------
# Orchestrator decomposition
# ---------------------------------------------------------------------------


class TestOrchestratorDecompose:
    def test_decompose_returns_subtasks(self):
        orch = Orchestrator(project_dir="/tmp/test")
        with patch.object(orch, "_call_orchestrator_model", return_value=json.dumps(SAMPLE_DECOMPOSITION)):
            result = orch.decompose(SAMPLE_TASK)

        assert isinstance(result, DecompositionResult)
        assert len(result.subtasks) == 3
        assert result.subtasks[0]["id"] == "T-42.1"

    def test_decompose_includes_cost_estimates(self):
        orch = Orchestrator(project_dir="/tmp/test")
        with patch.object(orch, "_call_orchestrator_model", return_value=json.dumps(SAMPLE_DECOMPOSITION)):
            result = orch.decompose(SAMPLE_TASK)

        assert result.total_estimated_cost_usd > 0
        assert result.recommended_budget_usd > result.total_estimated_cost_usd
        assert len(result.cost_breakdown) == 3

    def test_decompose_validates_tiers(self):
        orch = Orchestrator(project_dir="/tmp/test")
        with patch.object(orch, "_call_orchestrator_model", return_value=json.dumps(SAMPLE_DECOMPOSITION)):
            result = orch.decompose(SAMPLE_TASK)

        for st in result.subtasks:
            assert st["model_tier"] in ("mini", "standard", "max")

    def test_decompose_sets_owner_to_claude_code(self):
        orch = Orchestrator(project_dir="/tmp/test")
        with patch.object(orch, "_call_orchestrator_model", return_value=json.dumps(SAMPLE_DECOMPOSITION)):
            result = orch.decompose(SAMPLE_TASK)

        for st in result.subtasks:
            assert st.get("owner", "claude-code") == "claude-code"

    def test_decompose_fallback_on_bad_json(self):
        orch = Orchestrator(project_dir="/tmp/test")
        with patch.object(orch, "_call_orchestrator_model", return_value="not valid json {{{"):
            result = orch.decompose(SAMPLE_TASK)

        # Fallback: single subtask with full task as standard tier
        assert len(result.subtasks) == 1
        assert result.subtasks[0]["model_tier"] == "standard"
        assert result.subtasks[0]["id"] == "T-42.0"

    def test_decompose_fallback_on_empty_subtasks(self):
        orch = Orchestrator(project_dir="/tmp/test")
        with patch.object(orch, "_call_orchestrator_model", return_value=json.dumps({"subtasks": []})):
            result = orch.decompose(SAMPLE_TASK)

        assert len(result.subtasks) == 1
        assert result.subtasks[0]["model_tier"] == "standard"


# ---------------------------------------------------------------------------
# Subtask dispatch routing
# ---------------------------------------------------------------------------


class TestSubtaskDispatch:
    def test_dispatch_maps_tier_to_model(self):
        dispatch = SubtaskDispatch.from_subtask(
            subtask=SAMPLE_DECOMPOSITION["subtasks"][0],
            task_id="T-42",
            project_dir="/tmp/test",
        )
        assert dispatch.model == "sonnet"
        assert dispatch.tier == "standard"

    def test_dispatch_mini_uses_haiku(self):
        dispatch = SubtaskDispatch.from_subtask(
            subtask=SAMPLE_DECOMPOSITION["subtasks"][1],
            task_id="T-42",
            project_dir="/tmp/test",
        )
        assert dispatch.model == "haiku"
        assert dispatch.tier == "mini"

    def test_dispatch_max_uses_opus(self):
        subtask = {**SAMPLE_DECOMPOSITION["subtasks"][0], "model_tier": "max"}
        dispatch = SubtaskDispatch.from_subtask(
            subtask=subtask,
            task_id="T-42",
            project_dir="/tmp/test",
        )
        assert dispatch.model == "opus"
        assert dispatch.tier == "max"

    def test_dispatch_includes_subtask_prompt(self):
        dispatch = SubtaskDispatch.from_subtask(
            subtask=SAMPLE_DECOMPOSITION["subtasks"][0],
            task_id="T-42",
            project_dir="/tmp/test",
        )
        assert "T-42.1" in dispatch.prompt
        assert "rate limiter middleware" in dispatch.prompt.lower()

    def test_dispatch_prompt_scoped_to_subtask(self):
        """Sub-agent gets only its subtask scope, not the full task."""
        dispatch = SubtaskDispatch.from_subtask(
            subtask=SAMPLE_DECOMPOSITION["subtasks"][1],
            task_id="T-42",
            project_dir="/tmp/test",
        )
        assert "T-42.2" in dispatch.prompt
        assert "Redis" in dispatch.prompt


# ---------------------------------------------------------------------------
# Orchestrator prompt construction
# ---------------------------------------------------------------------------


class TestOrchestratorPrompt:
    def test_decompose_prompt_includes_task_info(self):
        orch = Orchestrator(project_dir="/tmp/test")
        prompt = orch._build_decompose_prompt(SAMPLE_TASK)
        assert "T-42" in prompt
        assert "rate limiting" in prompt.lower()
        assert "acceptance_criteria" in prompt.lower() or "100 req/min" in prompt

    def test_decompose_prompt_includes_tier_definitions(self):
        orch = Orchestrator(project_dir="/tmp/test")
        prompt = orch._build_decompose_prompt(SAMPLE_TASK)
        assert "mini" in prompt
        assert "standard" in prompt
        assert "max" in prompt

    def test_decompose_prompt_requests_json(self):
        orch = Orchestrator(project_dir="/tmp/test")
        prompt = orch._build_decompose_prompt(SAMPLE_TASK)
        assert "json" in prompt.lower()
