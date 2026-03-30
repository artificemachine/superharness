"""Orchestrator engine — Opus decomposes tasks and routes to sub-agents.

The orchestrator (always Opus 4.6) evaluates a task, decomposes it into
subtasks, assigns model tiers (mini/standard/max), estimates cost, and
generates dispatch instructions for sub-agents (Haiku/Sonnet/Opus).
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Any

from superharness.engine.cost_estimator import (
    estimate_task_cost,
    CostEstimate,
)
from superharness.engine.model_router import MODEL_MAP

logger = logging.getLogger(__name__)

_ORCHESTRATOR_MODEL = "opus"  # Always the top-tier model
_DEFAULT_ESTIMATED_TOKENS = 30000
_FALLBACK_ESTIMATED_TOKENS = 50000
_ORCHESTRATOR_TIMEOUT = 60  # seconds — Opus needs more time than Sonnet

_DECOMPOSE_PROMPT = """\
You are an orchestrator for a multi-agent coding system.
Your job is to decompose a task into subtasks and assign each to the
cheapest model tier that can handle it correctly.

Model tiers (Claude Code):
- mini (Haiku $0.25/$1.25 per MTok): docs, config, boilerplate, schema updates, simple field additions
- standard (Sonnet $3/$15 per MTok): multi-file coding, refactoring, debugging, tests, features, API integration
- max (Opus $15/$75 per MTok): architecture design, cross-system migration, security audit, 5+ constraints, subtle edge cases

Rules:
1. Prefer cheaper tiers — only escalate when the subtask genuinely requires it
2. Each subtask must be independently executable by a sub-agent
3. Subtask IDs follow the pattern: <parent_id>.<N> (e.g., T-42.1, T-42.2)
4. Estimate total tokens (input + output) each subtask will consume
5. Include a brief rationale for tier choice

Task:
  ID: {task_id}
  Title: {title}
  Acceptance criteria:
{criteria}

Reply with JSON only (no markdown fences):
{{
  "subtasks": [
    {{
      "id": "<parent_id>.<N>",
      "title": "subtask description",
      "model_tier": "mini|standard|max",
      "estimated_tokens": <int>,
      "rationale": "why this tier"
    }}
  ]
}}
"""


@dataclass
class DecompositionResult:
    """Result of orchestrator task decomposition."""
    subtasks: list[dict[str, Any]]
    cost_breakdown: list[CostEstimate] = field(default_factory=list)
    total_estimated_cost_usd: float = 0.0
    recommended_budget_usd: float = 0.0


@dataclass
class SubtaskDispatch:
    """Dispatch instructions for a single sub-agent."""
    subtask_id: str
    parent_task_id: str
    model: str
    tier: str
    prompt: str
    project_dir: str
    estimated_tokens: int = 0

    @classmethod
    def from_subtask(
        cls,
        subtask: dict[str, Any],
        task_id: str,
        project_dir: str,
    ) -> SubtaskDispatch:
        tier = subtask.get("model_tier", "standard")
        model = MODEL_MAP.get("claude-code", {}).get(tier, "sonnet")

        prompt = (
            f"You are a sub-agent executing subtask {subtask['id']} "
            f"of parent task {task_id}.\n\n"
            f"Subtask: {subtask['title']}\n"
            f"Scope: Complete this specific subtask only. Do not work on other parts "
            f"of the parent task.\n\n"
            f"When done, update .superharness/contract.yaml to mark subtask "  # shipguard:ignore PY-007
            f"{subtask['id']} as done and append to .superharness/ledger.md."
        )

        return cls(
            subtask_id=subtask["id"],
            parent_task_id=task_id,
            model=model,
            tier=tier,
            prompt=prompt,
            project_dir=project_dir,
            estimated_tokens=subtask.get("estimated_tokens", 0),
        )


class Orchestrator:
    """Opus-level orchestrator that decomposes tasks for sub-agent dispatch."""

    def __init__(self, project_dir: str) -> None:
        self.project_dir = project_dir

    def decompose(self, task: dict[str, Any]) -> DecompositionResult:
        """Decompose a task into subtasks with model tier assignments.

        Calls the orchestrator model (Opus) to analyze the task,
        then validates and enriches the result with cost estimates.
        """
        prompt = self._build_decompose_prompt(task)
        raw = self._call_orchestrator_model(prompt)

        subtasks = self._parse_decomposition(raw, task)

        # Enrich with cost estimates
        cost_input = [
            {"model_tier": st["model_tier"], "estimated_tokens": st["estimated_tokens"]}
            for st in subtasks
        ]
        task_estimate = estimate_task_cost(cost_input)

        # Ensure owner is set
        for st in subtasks:
            st.setdefault("owner", "claude-code")

        return DecompositionResult(
            subtasks=subtasks,
            cost_breakdown=task_estimate.subtask_estimates,
            total_estimated_cost_usd=task_estimate.total_estimated_cost_usd,
            recommended_budget_usd=task_estimate.recommended_budget_usd,
        )

    def _build_decompose_prompt(self, task: dict[str, Any]) -> str:
        criteria = task.get("acceptance_criteria") or []
        criteria_str = "\n".join(f"    - {c}" for c in criteria) if criteria else "    (none)"

        return _DECOMPOSE_PROMPT.format(
            task_id=task.get("id", "unknown"),
            title=task.get("title", "untitled"),
            criteria=criteria_str,
        )

    def _call_orchestrator_model(self, prompt: str) -> str:
        """Call Opus via claude CLI to get decomposition."""
        try:
            result = subprocess.run(
                ["claude", "--model", _ORCHESTRATOR_MODEL, "-p", prompt],
                capture_output=True,
                text=True,
                timeout=_ORCHESTRATOR_TIMEOUT,
                check=False,
            )
            if result.returncode != 0:
                logger.warning("Orchestrator model call failed: %s", result.stderr)
                return ""
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.warning("Orchestrator model call error: %s", e)
            return ""

    def _parse_decomposition(
        self, raw: str, task: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Parse JSON decomposition, with fallback to single-subtask."""
        task_id = task.get("id", "unknown")

        if not raw:
            return self._fallback_subtask(task)

        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse orchestrator JSON, using fallback")
            return self._fallback_subtask(task)

        subtasks = data.get("subtasks", [])
        if not subtasks:
            return self._fallback_subtask(task)

        # Validate tiers
        valid_tiers = {"mini", "standard", "max"}
        for st in subtasks:
            if st.get("model_tier") not in valid_tiers:
                st["model_tier"] = "standard"
            if "estimated_tokens" not in st:
                st["estimated_tokens"] = _DEFAULT_ESTIMATED_TOKENS

        return subtasks

    def _fallback_subtask(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        """Fallback: treat the whole task as a single standard-tier subtask."""
        return [
            {
                "id": f"{task.get('id', 'unknown')}.0",
                "title": task.get("title", "untitled"),
                "model_tier": "standard",
                "estimated_tokens": _FALLBACK_ESTIMATED_TOKENS,
                "rationale": "Fallback — orchestrator decomposition unavailable",
            }
        ]
