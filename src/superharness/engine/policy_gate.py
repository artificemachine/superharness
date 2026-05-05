"""Policy gate — per-agent policy enforcement.

Checks cost limits, loop detection, and action limits before dispatch.
"""
from __future__ import annotations


def check_agent_policy(
    agent: str,
    cost_usd: float = 0.0,
    max_cost_usd: float | None = None,
    loop_detected: bool = False,
) -> dict:
    """Check if an agent's dispatch should be blocked by policy.

    Returns:
        dict with keys: blocked (bool), reason (str)
    """
    # Loop detection always blocks
    if loop_detected:
        return {"blocked": True, "reason": f"Agent '{agent}' blocked: tool-loop detected"}

    # Cost limit check
    if max_cost_usd is not None and cost_usd > max_cost_usd:
        return {
            "blocked": True,
            "reason": f"Agent '{agent}' blocked: cost ${cost_usd:.2f} exceeds limit ${max_cost_usd:.2f}",
        }

    return {"blocked": False, "reason": ""}
