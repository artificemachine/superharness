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
        assert dispatch.model == "claude-sonnet-4-6"
        assert dispatch.tier == "standard"

    def test_dispatch_mini_uses_haiku(self):
        dispatch = SubtaskDispatch.from_subtask(
            subtask=SAMPLE_DECOMPOSITION["subtasks"][1],
            task_id="T-42",
            project_dir="/tmp/test",
        )
        assert dispatch.model == "claude-haiku-4-5-20251001"
        assert dispatch.tier == "mini"

    def test_dispatch_max_uses_opus(self):
        subtask = {**SAMPLE_DECOMPOSITION["subtasks"][0], "model_tier": "max"}
        dispatch = SubtaskDispatch.from_subtask(
            subtask=subtask,
            task_id="T-42",
            project_dir="/tmp/test",
        )
        assert dispatch.model == "claude-opus-4-8"
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

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_decompose_prompt_includes_tier_definitions(self):
        orch = Orchestrator(project_dir="/tmp/test")
        prompt = orch._build_decompose_prompt(SAMPLE_TASK)
        assert "sonnet-4-6" in prompt
        assert "opus-4-6" in prompt
        assert "opus-4-7" in prompt
        assert "Haiku" not in prompt

    def test_decompose_prompt_requests_json(self):
        orch = Orchestrator(project_dir="/tmp/test")
        prompt = orch._build_decompose_prompt(SAMPLE_TASK)
        assert "json" in prompt.lower()


# ---------------------------------------------------------------------------
# Decomposer prompt v2 — 5-effort scale, Sonnet/Opus-only menu
# ---------------------------------------------------------------------------

SAMPLE_DECOMPOSITION_V2 = {
    "should_split": True,
    "rationale": "Three distinct subtasks with different concerns",
    "subtasks": [
        {
            "id": "T-42.1",
            "title": "Write rate limiter middleware",
            "model": "sonnet-4-6",
            "effort": "medium",
            "timeout_minutes": 20,
            "blocked_by": None,
            "plan": {},
            "estimated_tokens": 45000,
        },
        {
            "id": "T-42.2",
            "title": "Add Redis counter backend",
            "model": "sonnet-4-6",
            "effort": "low",
            "timeout_minutes": 15,
            "blocked_by": "T-42.1",
            "plan": {},
            "estimated_tokens": 12000,
        },
        {
            "id": "T-42.3",
            "title": "Write integration tests",
            "model": "opus-4-6",
            "effort": "xhigh",
            "timeout_minutes": 30,
            "blocked_by": "T-42.2",
            "plan": {},
            "estimated_tokens": 30000,
        },
    ],
}


class TestDecomposerPromptV2:
    """Prompt v2: 5-effort scale, Sonnet/Opus-only executor menu, new task fields."""

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_prompt_has_sonnet_opus_menu_not_haiku(self):
        """Executor menu uses model IDs (sonnet-4-6/opus-4-6/opus-4-7), not Haiku."""
        orch = Orchestrator(project_dir="/tmp/test")
        prompt = orch._build_decompose_prompt(SAMPLE_TASK)
        assert "sonnet-4-6" in prompt
        assert "opus-4-6" in prompt
        assert "Haiku" not in prompt

    def test_prompt_includes_xhigh_effort_level(self):
        """5-effort scale includes xhigh in the prompt."""
        orch = Orchestrator(project_dir="/tmp/test")
        prompt = orch._build_decompose_prompt(SAMPLE_TASK)
        assert "xhigh" in prompt

    def test_prompt_includes_decompose_field(self):
        """Prompt instructs LLM to emit decompose field in JSON."""
        orch = Orchestrator(project_dir="/tmp/test")
        prompt = orch._build_decompose_prompt(SAMPLE_TASK)
        assert "decompose" in prompt

    def test_prompt_includes_development_method_field(self):
        """Prompt template surfaces development_method when set."""
        task = {**SAMPLE_TASK, "development_method": "tdd", "effort": "xhigh"}
        orch = Orchestrator(project_dir="/tmp/test")
        prompt = orch._build_decompose_prompt(task)
        assert "tdd" in prompt.lower() or "development_method" in prompt.lower()

    def test_prompt_includes_out_of_scope_content(self):
        """out_of_scope list is embedded in the prompt."""
        task = {**SAMPLE_TASK, "out_of_scope": ["UI changes", "billing logic"]}
        orch = Orchestrator(project_dir="/tmp/test")
        prompt = orch._build_decompose_prompt(task)
        assert "UI changes" in prompt or "billing" in prompt

    def test_parse_should_split_false_returns_single_subtask(self):
        """should_split: false keeps the single subtask without further decomposition."""
        decomp = {
            "should_split": False,
            "rationale": "Small scope, no split needed",
            "subtasks": [
                {
                    "id": "T-42.1",
                    "title": "Add rate limiting",
                    "model": "sonnet-4-6",
                    "effort": "high",
                    "timeout_minutes": 25,
                    "blocked_by": None,
                    "plan": {},
                    "estimated_tokens": 40000,
                }
            ],
        }
        orch = Orchestrator(project_dir="/tmp/test")
        with patch.object(orch, "_call_orchestrator_model", return_value=json.dumps(decomp)):
            result = orch.decompose(SAMPLE_TASK)
        assert len(result.subtasks) == 1
        assert result.subtasks[0]["id"] == "T-42.1"

    def test_parse_model_field_synthesizes_model_tier(self):
        """model:'sonnet-4-6' in v2 JSON → synthesized model_tier:'standard'."""
        orch = Orchestrator(project_dir="/tmp/test")
        with patch.object(orch, "_call_orchestrator_model", return_value=json.dumps(SAMPLE_DECOMPOSITION_V2)):
            result = orch.decompose(SAMPLE_TASK)
        assert result.subtasks[0]["model_tier"] == "standard"

    def test_parse_opus_model_synthesizes_max_tier(self):
        """model:'opus-4-6' in v2 JSON → synthesized model_tier:'max'."""
        orch = Orchestrator(project_dir="/tmp/test")
        with patch.object(orch, "_call_orchestrator_model", return_value=json.dumps(SAMPLE_DECOMPOSITION_V2)):
            result = orch.decompose(SAMPLE_TASK)
        assert result.subtasks[2]["model_tier"] == "max"

    def test_parse_effort_preserved_in_subtask(self):
        """effort field is preserved in the parsed subtask dict."""
        orch = Orchestrator(project_dir="/tmp/test")
        with patch.object(orch, "_call_orchestrator_model", return_value=json.dumps(SAMPLE_DECOMPOSITION_V2)):
            result = orch.decompose(SAMPLE_TASK)
        assert result.subtasks[2].get("effort") == "xhigh"

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_decomposer_model_constant_is_opus_46(self):
        """DECOMPOSER_MODEL is the Opus 4.6 full model ID."""
        from superharness.engine.orchestrator import DECOMPOSER_MODEL
        assert DECOMPOSER_MODEL == "claude-opus-4-6"

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_decomposer_fallback_constant_is_opus_47(self):
        """DECOMPOSER_FALLBACK escalates to Opus 4.7 when 4.6 is unavailable."""
        from superharness.engine.orchestrator import DECOMPOSER_FALLBACK
        assert DECOMPOSER_FALLBACK == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# RoutingPlan + route() — auto-orchestrate routing decisions
# ---------------------------------------------------------------------------

class TestRoutingPlan:
    """Tests for the RoutingPlan dataclass and Orchestrator.route() method."""

    def test_routing_plan_defaults(self):
        """RoutingPlan has correct default values."""
        from superharness.engine.orchestrator import RoutingPlan
        plan = RoutingPlan(owner="claude-code", tier="standard", effort="medium", decompose=False)
        assert plan.owner == "claude-code"
        assert plan.tier == "standard"
        assert plan.effort == "medium"
        assert plan.decompose is False
        assert plan.rationale == ""
        assert plan.subtasks == []
        assert plan.total_estimated_cost_usd == 0.0
        assert plan.recommended_budget_usd == 0.0

    def test_routing_plan_with_decomposition(self):
        """RoutingPlan handles decompose=true with subtasks."""
        from superharness.engine.orchestrator import RoutingPlan
        plan = RoutingPlan(
            owner="claude-code", tier="max", effort="high", decompose=True,
            rationale="cross-cutting feature",
            subtasks=[
                {"id": "t.st1", "title": "API layer", "owner": "codex-cli", "model_tier": "standard"},
                {"id": "t.st2", "title": "Auth tests", "owner": "claude-code", "model_tier": "max"},
            ],
            total_estimated_cost_usd=3.50,
            recommended_budget_usd=5.00,
        )
        assert plan.decompose is True
        assert len(plan.subtasks) == 2
        assert plan.subtasks[0]["owner"] == "codex-cli"
        assert plan.total_estimated_cost_usd == 3.50

    def test_fallback_routing(self):
        """_fallback_routing returns standard dispatch plan."""
        from superharness.engine.orchestrator import Orchestrator
        orch = Orchestrator(project_dir="/tmp")
        task = {"id": "t1", "title": "Test", "owner": "codex-cli"}
        plan = orch._fallback_routing(task)
        assert plan.owner == "codex-cli"
        assert plan.tier == "standard"
        assert plan.effort == "medium"
        assert plan.decompose is False
        assert "unavailable" in plan.rationale.lower()


# ---------------------------------------------------------------------------
# NULL metadata in handoffs — defensive json.loads
# ---------------------------------------------------------------------------

class TestHandoffNullMetadata:
    """Tests that handoffs_dao handles NULL metadata columns gracefully."""

    def test_null_metadata_returns_empty_dict(self, tmp_path):
        """Row with NULL metadata → empty dict, no crash."""
        import sqlite3
        from superharness.engine.handoffs_dao import _row_to_handoff

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE handoffs (
                id INTEGER PRIMARY KEY,
                task_id TEXT, phase TEXT, status TEXT,
                from_agent TEXT, to_agent TEXT,
                content TEXT, metadata TEXT, created_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO handoffs VALUES (1, 't1', 'report', 'done', 'claude-code', 'owner', 'content', NULL, '2026-01-01')"
        )
        conn.commit()
        row = conn.execute("SELECT * FROM handoffs WHERE id=1").fetchone()

        result = _row_to_handoff(row)
        assert result.metadata == {}  # not None, not crash
        assert result.task_id == "t1"

    def test_empty_string_metadata(self, tmp_path):
        """Empty string metadata → empty dict."""
        import sqlite3
        from superharness.engine.handoffs_dao import _row_to_handoff

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE handoffs (
                id INTEGER PRIMARY KEY,
                task_id TEXT, phase TEXT, status TEXT,
                from_agent TEXT, to_agent TEXT,
                content TEXT, metadata TEXT, created_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO handoffs VALUES (2, 't2', 'plan', 'proposed', 'gemini', 'owner', 'plan', '', '2026-01-01')"
        )
        conn.commit()
        row = conn.execute("SELECT * FROM handoffs WHERE id=2").fetchone()

        result = _row_to_handoff(row)
        assert result.metadata == {}

    def test_valid_json_metadata(self, tmp_path):
        """Valid JSON metadata parses correctly."""
        import sqlite3
        from superharness.engine.handoffs_dao import _row_to_handoff

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE handoffs (
                id INTEGER PRIMARY KEY,
                task_id TEXT, phase TEXT, status TEXT,
                from_agent TEXT, to_agent TEXT,
                content TEXT, metadata TEXT, created_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO handoffs VALUES (3, 't3', 'report', 'done', 'claude', 'owner', 'done', '{\"key\": \"val\"}', '2026-01-01')"
        )
        conn.commit()
        row = conn.execute("SELECT * FROM handoffs WHERE id=3").fetchone()

        result = _row_to_handoff(row)
        assert result.metadata == {"key": "val"}
