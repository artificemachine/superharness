"""Pre-flight cost estimation for orchestrator task decomposition.

Estimates token usage and cost per subtask based on model tier,
using the same pricing table as sdk_runner.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from superharness.engine.sdk_runner import MODEL_PRICING as PRICING

_TIER_TO_MODEL: dict[str, str] = {
    "mini":     "claude-haiku-4-5-20251001",
    "standard": "claude-sonnet-4-6",
    "max":      "claude-opus-4-7",
    "max-1m":   "claude-opus-4-7[1m]",
    "flash":    "flash",
    "pro":      "pro",
    "ultra":    "ultra",
}

_DEFAULT_INPUT_RATIO = 0.6  # 60% input, 40% output


def tier_to_model_id(tier: str) -> str:
    """Map a model tier to the full model ID."""
    return _TIER_TO_MODEL.get(tier, "claude-sonnet-4-6")


@dataclass
class CostEstimate:
    """Cost estimate for a single subtask."""
    model_id: str
    tier: str
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float


@dataclass
class TaskCostEstimate:
    """Aggregated cost estimate for a full task with subtasks."""
    subtask_estimates: list[CostEstimate] = field(default_factory=list)
    total_estimated_cost_usd: float = 0.0
    recommended_budget_usd: float = 0.0


def estimate_subtask_cost(
    tier: str,
    estimated_tokens: int,
    input_ratio: float = _DEFAULT_INPUT_RATIO,
) -> CostEstimate:
    """Estimate cost for a subtask given tier and total token estimate."""
    model_id = tier_to_model_id(tier)
    pricing = PRICING.get(model_id, PRICING["claude-sonnet-4-6"])

    input_tokens = int(estimated_tokens * input_ratio)
    output_tokens = estimated_tokens - input_tokens

    cost = (input_tokens / 1_000_000) * pricing["input"] + \
           (output_tokens / 1_000_000) * pricing["output"]

    return CostEstimate(
        model_id=model_id,
        tier=tier,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        estimated_cost_usd=cost,
    )


def estimate_task_cost(
    subtasks: list[dict],
    budget_buffer: float = 1.5,
) -> TaskCostEstimate:
    """Estimate total cost for a task with multiple subtasks.

    Args:
        subtasks: List of dicts with 'model_tier' and 'estimated_tokens' keys.
        budget_buffer: Multiplier for recommended budget (default 1.5x).

    Returns:
        TaskCostEstimate with per-subtask and total estimates.
    """
    if not subtasks:
        return TaskCostEstimate()

    estimates = []
    for i, st in enumerate(subtasks):
        tier = st.get("model_tier")
        tokens = st.get("estimated_tokens")
        if tier is None or tokens is None:
            raise ValueError(
                f"subtasks[{i}] missing required key(s): "
                f"{'model_tier' if tier is None else 'estimated_tokens'}"
            )
        est = estimate_subtask_cost(tier=tier, estimated_tokens=int(tokens))
        estimates.append(est)

    total = sum(e.estimated_cost_usd for e in estimates)
    return TaskCostEstimate(
        subtask_estimates=estimates,
        total_estimated_cost_usd=total,
        recommended_budget_usd=total * budget_buffer,
    )
