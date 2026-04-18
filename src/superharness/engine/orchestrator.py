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
from superharness.engine.taxonomy import VALID_EFFORTS

logger = logging.getLogger(__name__)

DECOMPOSER_MODEL = "claude-opus-4-6"
DECOMPOSER_FALLBACK = "claude-opus-4-7"  # escalate when 4.6 unavailable; log warning

_ORCHESTRATOR_MODEL = DECOMPOSER_MODEL
_DEFAULT_ESTIMATED_TOKENS = 30000
_FALLBACK_ESTIMATED_TOKENS = 50000
_ORCHESTRATOR_TIMEOUT = 60

_MODEL_TO_TIER: dict[str, str] = {
    "sonnet-4-6": "standard",
    "opus-4-6":   "max",
    "opus-4-7":   "max",
}

_DECOMPOSE_PROMPT = """\
You are an orchestrator for a multi-agent coding system.
Your job is to decompose a task into subtasks and assign each to the
right model and effort level.

Available executors (pick ONE per subtask):
- sonnet-4-6 ($3/$15 per MTok)   — default for ~80% of subtasks
- opus-4-6   ($15/$75 per MTok)  — complex core logic, security, cross-cutting concerns
- opus-4-7   ($15/$75 per MTok)  — reserve for the single irreversible subtask; max effort only

Effort levels: low | medium | high | xhigh | max
(low=bounded; medium=typical; high=complex; xhigh=cross-system; max=highest-stakes)

Rules:
1. Split decision:
   - effort=xhigh: evaluate split; typically 2-4 subtasks
   - effort=max: evaluate split; typically 3-6 subtasks
   - If AC <= 3 AND files <= 3: do NOT split (return 1 subtask = original, should_split=false)
2. Subtask IDs: <parent_id>.<N>
3. If development_method is set, shape subtasks around its phases (tdd: red/green/refactor etc.)
4. Respect out_of_scope — no subtask may violate it
5. Assign model + effort + timeout per subtask using the table above
6. Use blocked_by for sequential ordering; leave independent subtasks unblocked
7. Subtask model MUST be <= parent model (never escalate silently)
8. Subtask effort MUST be <= parent effort (never escalate silently)
9. Prefer sonnet-4-6 unless the subtask explicitly requires Opus-level judgment

Task:
  ID:                  {task_id}
  Title:               {title}
  Effort:              {effort}
  Development method:  {development_method}
  Test types:          {test_types}
  Acceptance criteria:
{criteria}
  Out of scope:        {out_of_scope}
  Definition of done:  {definition_of_done}
  Context:             {context}

Reply with JSON only (no markdown fences):
{{
  "should_split": true,
  "rationale": "...",
  "subtasks": [
    {{
      "id": "<parent_id>.<N>",
      "title": "...",
      "model": "sonnet-4-6 | opus-4-6 | opus-4-7",
      "effort": "low | medium | high | xhigh | max",
      "timeout_minutes": <int>,
      "blocked_by": "<parent_id>.<N-1>" | null,
      "plan": {{}},
      "estimated_tokens": <int>
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

        out_of_scope = task.get("out_of_scope") or []
        out_str = ", ".join(out_of_scope) if out_of_scope else "none"

        test_types = task.get("test_types") or []
        test_str = ", ".join(test_types) if test_types else "none"

        return _DECOMPOSE_PROMPT.format(
            task_id=task.get("id", "unknown"),
            title=task.get("title", "untitled"),
            effort=task.get("effort") or "medium",
            development_method=task.get("development_method") or "none",
            test_types=test_str,
            criteria=criteria_str,
            out_of_scope=out_str,
            definition_of_done=", ".join(task.get("definition_of_done") or []) or "none",
            context=task.get("context") or "none",
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

        valid_tiers = {"mini", "standard", "max"}
        valid_efforts = set(VALID_EFFORTS)
        for st in subtasks:
            # v2 schema: synthesize model_tier from full model ID
            if "model" in st and "model_tier" not in st:
                st["model_tier"] = _MODEL_TO_TIER.get(st["model"], "standard")
            elif st.get("model_tier") not in valid_tiers:
                st["model_tier"] = "standard"

            if "estimated_tokens" not in st:
                st["estimated_tokens"] = _DEFAULT_ESTIMATED_TOKENS

            # Clamp effort to valid set
            if "effort" in st and st["effort"] not in valid_efforts:
                del st["effort"]

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
