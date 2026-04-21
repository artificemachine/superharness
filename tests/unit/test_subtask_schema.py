"""Tests for Subtask schema and ContractTask subtask integration."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from superharness.engine.schemas import (
    ContractTask,
    ModelTier,
    Subtask,
    SubtaskStatus,
)


# ---------------------------------------------------------------------------
# ModelTier enum
# ---------------------------------------------------------------------------


class TestModelTier:
    def test_valid_tiers(self):
        assert ModelTier.mini == "mini"
        assert ModelTier.standard == "standard"
        assert ModelTier.max == "max"

    def test_all_tiers_present(self):
        assert set(t.value for t in ModelTier) == {"mini", "standard", "max"}


# ---------------------------------------------------------------------------
# SubtaskStatus enum
# ---------------------------------------------------------------------------


class TestSubtaskStatus:
    def test_valid_statuses(self):
        assert SubtaskStatus.pending == "pending"
        assert SubtaskStatus.in_progress == "in_progress"
        assert SubtaskStatus.done == "done"
        assert SubtaskStatus.failed == "failed"


# ---------------------------------------------------------------------------
# Subtask model
# ---------------------------------------------------------------------------

VALID_SUBTASK = {
    "id": "T-42.1",
    "title": "Write rate limiter middleware",
    "model_tier": "standard",
    "owner": "claude-code",
    "estimated_tokens": 45000,
    "estimated_cost_usd": 0.28,
}


class TestSubtask:
    def test_valid_subtask(self):
        st = Subtask.model_validate(VALID_SUBTASK)
        assert st.id == "T-42.1"
        assert st.model_tier == ModelTier.standard
        assert st.owner == "claude-code"
        assert st.estimated_tokens == 45000
        assert st.estimated_cost_usd == 0.28
        assert st.status == SubtaskStatus.pending  # default

    def test_all_tiers_accepted(self):
        for tier in ("mini", "standard", "max"):
            st = Subtask.model_validate({**VALID_SUBTASK, "model_tier": tier})
            assert st.model_tier.value == tier

    def test_invalid_tier_raises(self):
        with pytest.raises(ValidationError):
            Subtask.model_validate({**VALID_SUBTASK, "model_tier": "ultra"})

    def test_cancelled_status_is_valid(self):
        st = Subtask.model_validate({**VALID_SUBTASK, "status": "cancelled"})
        assert st.status == SubtaskStatus.cancelled
        assert st.status.value == "cancelled"

    def test_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            Subtask.model_validate({**VALID_SUBTASK, "status": "retired"})

    def test_status_transitions(self):
        for status in ("pending", "in_progress", "done", "failed", "cancelled"):
            st = Subtask.model_validate({**VALID_SUBTASK, "status": status})
            assert st.status.value == status

    def test_missing_required_field_raises(self):
        incomplete = {"id": "T-42.1", "title": "test"}
        with pytest.raises(ValidationError):
            Subtask.model_validate(incomplete)

    def test_optional_actual_fields(self):
        st = Subtask.model_validate({
            **VALID_SUBTASK,
            "actual_tokens": 50000,
            "actual_cost_usd": 0.35,
            "model_used": "claude-sonnet-4-6",
        })
        assert st.actual_tokens == 50000
        assert st.actual_cost_usd == 0.35
        assert st.model_used == "claude-sonnet-4-6"

    def test_defaults_for_optional_fields(self):
        st = Subtask.model_validate(VALID_SUBTASK)
        assert st.actual_tokens is None
        assert st.actual_cost_usd is None
        assert st.model_used is None


# ---------------------------------------------------------------------------
# ContractTask with subtasks
# ---------------------------------------------------------------------------

VALID_TASK = {
    "id": "T-42",
    "title": "Add rate limiting",
    "owner": "claude-code",
    "status": "todo",
}


class TestContractTaskSubtasks:
    def test_task_without_subtasks(self):
        task = ContractTask.model_validate(VALID_TASK)
        assert task.subtasks == []
        assert task.estimated_cost_usd is None
        assert task.budget_usd is None

    def test_task_with_subtasks(self):
        task = ContractTask.model_validate({
            **VALID_TASK,
            "subtasks": [VALID_SUBTASK],
            "estimated_cost_usd": 0.28,
            "budget_usd": 0.50,
        })
        assert len(task.subtasks) == 1
        assert task.subtasks[0].id == "T-42.1"
        assert task.subtasks[0].model_tier == ModelTier.standard
        assert task.estimated_cost_usd == 0.28
        assert task.budget_usd == 0.50

    def test_task_with_multiple_subtasks(self):
        subtasks = [
            {**VALID_SUBTASK, "id": "T-42.1", "model_tier": "standard"},
            {**VALID_SUBTASK, "id": "T-42.2", "model_tier": "mini", "estimated_tokens": 12000, "estimated_cost_usd": 0.02},
            {**VALID_SUBTASK, "id": "T-42.3", "model_tier": "max", "estimated_tokens": 80000, "estimated_cost_usd": 2.50},
        ]
        task = ContractTask.model_validate({**VALID_TASK, "subtasks": subtasks})
        assert len(task.subtasks) == 3
        tiers = [st.model_tier.value for st in task.subtasks]
        assert tiers == ["standard", "mini", "max"]

    def test_task_subtask_invalid_tier_raises(self):
        bad_subtask = {**VALID_SUBTASK, "model_tier": "ultra"}
        with pytest.raises(ValidationError):
            ContractTask.model_validate({**VALID_TASK, "subtasks": [bad_subtask]})

    def test_subtask_yaml_round_trip(self):
        """Subtasks survive YAML serialization."""
        import yaml
        task = ContractTask.model_validate({
            **VALID_TASK,
            "subtasks": [VALID_SUBTASK],
            "estimated_cost_usd": 0.28,
            "budget_usd": 0.50,
        })
        dumped = yaml.safe_dump(task.model_dump(mode="json"), default_flow_style=False)
        loaded = yaml.safe_load(dumped)
        restored = ContractTask.model_validate(loaded)
        assert len(restored.subtasks) == 1
        assert restored.subtasks[0].model_tier.value == "standard"
        assert restored.estimated_cost_usd == 0.28
