"""Tests for cost estimator engine."""
from __future__ import annotations

import pytest

from superharness.engine.cost_estimator import (
    PRICING,
    CostEstimate,
    estimate_subtask_cost,
    estimate_task_cost,
    tier_to_model_id,
)


# ---------------------------------------------------------------------------
# Pricing table
# ---------------------------------------------------------------------------


class TestPricing:
    def test_all_models_have_pricing(self):
        expected = {
            "claude-opus-4-7", "claude-opus-4-7[1m]", "claude-opus-4-6",
            "claude-sonnet-4-6", "claude-haiku-4-5-20251001",
        }
        assert expected == set(PRICING.keys())

    def test_pricing_has_input_output(self):
        for model, prices in PRICING.items():
            assert "input" in prices, f"{model} missing input price"
            assert "output" in prices, f"{model} missing output price"
            assert prices["input"] > 0
            assert prices["output"] > 0


# ---------------------------------------------------------------------------
# tier_to_model_id
# ---------------------------------------------------------------------------


class TestTierToModelId:
    def test_mini_maps_to_haiku(self):
        assert tier_to_model_id("mini") == "claude-haiku-4-5-20251001"

    def test_standard_maps_to_sonnet(self):
        assert tier_to_model_id("standard") == "claude-sonnet-4-6"

    def test_max_maps_to_opus_47(self):
        assert tier_to_model_id("max") == "claude-opus-4-7"

    def test_max_1m_maps_to_opus_47_1m(self):
        assert tier_to_model_id("max-1m") == "claude-opus-4-7[1m]"

    def test_unknown_defaults_to_sonnet(self):
        assert tier_to_model_id("unknown") == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# estimate_subtask_cost
# ---------------------------------------------------------------------------


class TestEstimateSubtaskCost:
    def test_haiku_cost(self):
        est = estimate_subtask_cost("mini", estimated_tokens=10000)
        assert est.model_id == "claude-haiku-4-5-20251001"
        assert est.estimated_input_tokens > 0
        assert est.estimated_output_tokens > 0
        assert est.estimated_cost_usd > 0
        # Haiku should be cheapest
        assert est.estimated_cost_usd < 0.05

    def test_sonnet_cost(self):
        est = estimate_subtask_cost("standard", estimated_tokens=50000)
        assert est.model_id == "claude-sonnet-4-6"
        assert est.estimated_cost_usd > 0

    def test_opus_cost(self):
        est = estimate_subtask_cost("max", estimated_tokens=50000)
        assert est.model_id == "claude-opus-4-7"
        assert est.estimated_cost_usd > 0.50

    def test_cost_scales_with_tokens(self):
        small = estimate_subtask_cost("standard", estimated_tokens=10000)
        large = estimate_subtask_cost("standard", estimated_tokens=100000)
        assert large.estimated_cost_usd > small.estimated_cost_usd

    def test_opus_more_expensive_than_sonnet(self):
        sonnet = estimate_subtask_cost("standard", estimated_tokens=50000)
        opus = estimate_subtask_cost("max", estimated_tokens=50000)
        assert opus.estimated_cost_usd > sonnet.estimated_cost_usd

    def test_haiku_cheaper_than_sonnet(self):
        haiku = estimate_subtask_cost("mini", estimated_tokens=50000)
        sonnet = estimate_subtask_cost("standard", estimated_tokens=50000)
        assert haiku.estimated_cost_usd < sonnet.estimated_cost_usd

    def test_custom_io_ratio(self):
        # 80% input, 20% output (default is 60/40)
        est = estimate_subtask_cost("standard", estimated_tokens=100000, input_ratio=0.8)
        # More input-heavy should be cheaper (input costs less than output)
        est_default = estimate_subtask_cost("standard", estimated_tokens=100000)
        assert est.estimated_cost_usd < est_default.estimated_cost_usd


# ---------------------------------------------------------------------------
# estimate_task_cost
# ---------------------------------------------------------------------------


class TestEstimateTaskCost:
    def test_single_subtask(self):
        subtasks = [{"model_tier": "standard", "estimated_tokens": 50000}]
        total = estimate_task_cost(subtasks)
        assert total.total_estimated_cost_usd > 0
        assert len(total.subtask_estimates) == 1
        assert total.recommended_budget_usd > total.total_estimated_cost_usd

    def test_multiple_subtasks_sum(self):
        subtasks = [
            {"model_tier": "mini", "estimated_tokens": 10000},
            {"model_tier": "standard", "estimated_tokens": 50000},
            {"model_tier": "max", "estimated_tokens": 30000},
        ]
        total = estimate_task_cost(subtasks)
        assert len(total.subtask_estimates) == 3
        individual_sum = sum(e.estimated_cost_usd for e in total.subtask_estimates)
        assert abs(total.total_estimated_cost_usd - individual_sum) < 0.001

    def test_budget_has_buffer(self):
        subtasks = [{"model_tier": "standard", "estimated_tokens": 50000}]
        total = estimate_task_cost(subtasks)
        # Budget should be 1.5x the estimate by default
        assert total.recommended_budget_usd == pytest.approx(
            total.total_estimated_cost_usd * 1.5, rel=0.01
        )

    def test_custom_budget_buffer(self):
        subtasks = [{"model_tier": "standard", "estimated_tokens": 50000}]
        total = estimate_task_cost(subtasks, budget_buffer=2.0)
        assert total.recommended_budget_usd == pytest.approx(
            total.total_estimated_cost_usd * 2.0, rel=0.01
        )

    def test_empty_subtasks(self):
        total = estimate_task_cost([])
        assert total.total_estimated_cost_usd == 0.0
        assert total.recommended_budget_usd == 0.0
        assert total.subtask_estimates == []

    def test_all_haiku_cheaper_than_all_opus(self):
        haiku_subtasks = [{"model_tier": "mini", "estimated_tokens": 50000}] * 3
        opus_subtasks = [{"model_tier": "max", "estimated_tokens": 50000}] * 3
        haiku_total = estimate_task_cost(haiku_subtasks)
        opus_total = estimate_task_cost(opus_subtasks)
        assert haiku_total.total_estimated_cost_usd < opus_total.total_estimated_cost_usd
