"""Orchestrator engine — cross-agent task decomposition and model routing.

The orchestrator selects the best available max-tier model from any agent
(Claude Opus, Codex GPT-5.4, Gemini Ultra) to decompose a task into subtasks,
assigns model tiers (mini/standard/max), estimates cost, and generates
dispatch instructions for sub-agents.

Orchestrator model selection uses random exploration with quality tracking:
each model in the chain gets scored on decomposition success rate. Over time,
preferred models get higher selection weight.
"""
from __future__ import annotations

import json
import logging
import random
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

DECOMPOSER_MODEL = "claude-opus-4-7"
DECOMPOSER_FALLBACK = "claude-opus-4-6"  # kept as single-model fallback within claude

# Cross-agent orchestrator chain: (binary, model_id, label)
# Tries the best model from each agent. Randomly shuffled per call so
# different models get a chance — quality scores accumulate over time.
_ORCHESTRATOR_CHAIN: list[tuple[str, str, str]] = [
    ("claude", "claude-opus-4-7",   "Claude Opus 4.7 (max)"),
    ("claude", "claude-opus-4-6",   "Claude Opus 4.6 (fallback)"),
    ("codex",  "gpt-5.4",           "Codex GPT-5.4 (max)"),
    ("gemini", "gemini-ultra",      "Gemini Ultra (max)"),
]

# Quality scores per model: {model_id: {successes: int, failures: int, last_used: iso}}
# Higher success rate = higher selection weight for future decompositions.
# Initialized with neutral scores so new models get a fair chance.
_orchestrator_scores: dict[str, dict[str, Any]] = {}


def _shuffle_chain() -> list[tuple[str, str, str]]:
    """Shuffle the chain randomly, biased by quality scores.

    Models with higher success rates get duplicated entries in the pool,
    giving them proportionally higher chance of being picked first.
    """
    # Build a weighted pool: each model appears 1 + ceil(success_rate * 4) times
    pool: list[tuple[str, str, str]] = []
    for entry in _ORCHESTRATOR_CHAIN:
        binary, model, label = entry
        score = _orchestrator_scores.get(model, {})
        successes = score.get("successes", 0)
        failures = score.get("failures", 0)
        total = successes + failures
        # New models (no history) get a bonus so they get tried
        if total == 0:
            weight = 3  # generous for exploration
        else:
            rate = successes / total
            weight = 1 + int(rate * 4)  # 1-5 entries
        pool.extend([entry] * weight)
    random.shuffle(pool)
    # Deduplicate: keep first occurrence of each model
    seen: set[str] = set()
    result: list[tuple[str, str, str]] = []
    for entry in pool:
        if entry[1] not in seen:
            seen.add(entry[1])
            result.append(entry)
    return result


def _record_orchestrator_score(model: str, success: bool) -> None:
    """Update quality score for an orchestrator model."""
    from datetime import datetime, timezone
    score = _orchestrator_scores.setdefault(model, {"successes": 0, "failures": 0})
    if success:
        score["successes"] += 1
    else:
        score["failures"] += 1
    score["last_used"] = datetime.now(timezone.utc).isoformat()

_ORCHESTRATOR_MODEL = DECOMPOSER_MODEL
_DEFAULT_ESTIMATED_TOKENS = 30000
_FALLBACK_ESTIMATED_TOKENS = 50000
_ORCHESTRATOR_TIMEOUT = 60

_MODEL_TO_TIER: dict[str, str] = {
    # claude-code
    "haiku-4-5":     "mini",
    "sonnet-4-6":    "standard",
    "sonnet-4-5":    "standard",
    "opus-4-6":      "max",
    "opus-4-7":      "max",
    # codex-cli
    "codex-mini":    "mini",
    "codex":         "standard",
    "gpt-5.4":       "max",
    # gemini-cli
    "gemini-flash":  "mini",
    "gemini-pro":    "standard",
    "gemini-ultra":  "max",
}

_DECOMPOSE_PROMPT = """\
You are an orchestrator for a multi-agent coding system.
Your job is to decompose a task into subtasks and assign each to the right model and effort level.

Available executors across agents (pick ONE model per subtask):
  MINI tier (quick, cheap — simple edits, typo fixes, single-file changes):
    - haiku-4-5        ($0.25/$1.25 per MTok) — claude-code
    - gemini-2.0-flash ($0.10/$0.40 per MTok) — gemini-cli
    - gpt-5.1-codex-mini                     — codex-cli

  STANDARD tier (default for ~80% of subtasks — typical features, CRUD, tests):
    - sonnet-4-6       ($3/$15 per MTok)     — claude-code
    - gemini-2.0-pro   ($1.25/$5 per MTok)   — gemini-cli
    - gpt-5.3-codex                           — codex-cli

  MAX tier (complex logic, security, architecture, cross-cutting concerns):
    - opus-4-7         ($15/$75 per MTok)    — claude-code
    - gemini-ultra     ($15/$75 per MTok)    — gemini-cli
    - gpt-5.4                                — codex-cli

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
7. Subtask model tier MUST be <= parent model tier (never escalate silently)
8. Subtask effort MUST be <= parent effort (never escalate silently)
9. Prefer MINI or STANDARD models unless the subtask explicitly requires MAX-tier judgment
10. Route to the cheapest model at the assigned tier unless complexity demands a specific agent

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
      "model": "sonnet-4-6 | opus-4-7 | haiku-4-5 | gemini-2.0-flash | gemini-2.0-pro | gemini-ultra | gpt-5.1-codex-mini | gpt-5.3-codex | gpt-5.4",
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
        """Call the best available model across all agents for decomposition.

        Shuffles the orchestrator chain randomly (biased by quality scores)
        and tries each model in order. First successful response wins.
        Quality scores are recorded for future selection weighting.
        """
        from datetime import datetime, timezone

        chain = _shuffle_chain()
        for binary, model, label in chain:
            try:
                result = subprocess.run(
                    [binary, "--model", model, "-p", prompt],
                    capture_output=True,
                    text=True,
                    timeout=_ORCHESTRATOR_TIMEOUT,
                    check=False,
                )
                success = result.returncode == 0 and bool(result.stdout.strip())
                _record_orchestrator_score(model, success)

                if success:
                    logger.info("Orchestrator: %s (%s) succeeded", label, model)
                    return result.stdout.strip()
                logger.debug(
                    "Orchestrator: %s (%s) failed (rc=%d): %.200s",
                    label, model, result.returncode, result.stderr
                )
            except FileNotFoundError:
                _record_orchestrator_score(model, False)
                logger.debug("Orchestrator: %s binary not found, skipping", binary)
            except (subprocess.TimeoutExpired, OSError) as e:
                _record_orchestrator_score(model, False)
                logger.debug("Orchestrator: %s (%s) error: %s", label, model, e)

        logger.warning("Orchestrator: all models failed — decomposition skipped")
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
