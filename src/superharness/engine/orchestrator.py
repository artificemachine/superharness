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

DECOMPOSER_MODEL = "claude-opus-4-8"
DECOMPOSER_FALLBACK = "claude-opus-4-7"  # kept as single-model fallback within claude

# Cross-agent orchestrator chain: (binary, model_id, label)
# Tries the best model from each agent. Randomly shuffled per call so
# different models get a chance — quality scores accumulate over time.
_ORCHESTRATOR_CHAIN: list[tuple[str, str, str]] = [
    ("claude", "claude-opus-4-8",          "Claude Opus 4.8 (max)"),
    ("claude", "claude-opus-4-7",          "Claude Opus 4.7 (fallback)"),
    ("codex",  "gpt-5.5",                 "Codex GPT-5.5 (max)"),
    ("gemini", "gemini-3.1-pro-preview",   "Gemini 3.1 Pro (max)"),
    ("opencode", "deepseek/deepseek-v4-pro", "DeepSeek V4 Pro (max)"),
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


def _log_orchestrator_error(error: str) -> None:
    """Log an orchestrator error to the project's watcher error log. Never raises."""
    try:
        import logging
        logger.warning("Orchestrator error: %s", error)
    except Exception as e:
        logger.warning("orchestrator.py unexpected error: %s", e, exc_info=True)
        pass
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
    "opus-4-8":      "max",
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
Your job: for any task, decide WHO executes it, at WHAT tier, with WHAT effort, and whether to SPLIT into subtasks.

Available executors:
  claude-code:
    max:      opus-4-8       ($5/$25 per MTok)  — best reasoning, architecture, safety-critical
    standard: sonnet-4-6     ($3/$15 per MTok)  — solid code gen, balanced
    mini:     haiku-4-5      ($1/$5 per MTok)   — simple edits, typo fixes
    effort:   low | medium | high               (reasoning depth — Opus uses adaptive thinking)

  codex-cli:
    max:      gpt-5.5                          — strongest code generation
    standard: gpt-5.3-codex                    — balanced code work
    mini:     gpt-5.1-codex-mini               — quick fixes
    effort:   low | medium | high | xhigh      (model_reasoning_effort — xhigh for hardest)

  gemini-cli:
    max:      gemini-3.1-pro                   — fast, large context, latest
    standard: gemini-2.5-pro                   — solid general purpose
    mini:     gemini-2.5-flash                 — fast turnaround
    effort:   unsupported (gemini CLI has no effort/thinking flags)

  opencode:
    max:      deepseek-v4-pro                  — budget-friendly deep reasoning
    standard: deepseek-v4-flash                — fast, budget option
    mini:     deepseek-chat                    — cheapest
    effort:   unsupported (opencode CLI has no effort flag)

Owner selection rules:
  - Architecture, system design, safety, security   → claude-code
  - Heavy implementation, code generation           → codex-cli
  - Fast turnaround, large-context processing       → gemini-cli
  - Budget-constrained, non-critical                → opencode
  - Cross-cutting concerns                          → claude-code (orchestrates), codex-cli (builds)

Tier selection rules:
  - Security audit, data migration, auth, payouts   → max
  - New feature, refactor, test suite               → standard (escalate to max if >6 criteria)
  - Typo fix, doc update, simple chore              → mini
  - Discussion topic (design/architecture)          → max (needs deep reasoning)
  - Previously failed task                          → escalate one tier up

Effort selection rules (only for claude-code and codex-cli):
  - Safety, security, complex architecture          → high
  - Feature implementation, test writing            → medium
  - Chore, refactor, doc update                     → low

Split decision rules:
  - AC <= 3 AND files <= 3 → do NOT split (decompose: false)
  - AC > 3 OR files > 3    → split into 2-4 subtasks
  - Cross-cutting (multiple modules) → split into 3-6 subtasks
  - Discussion → do NOT split (multi-agent rounds, not subtasks)

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
  "owner": "claude-code | codex-cli | gemini-cli | opencode",
  "tier": "mini | standard | max",
  "effort": "low | medium | high | xhigh",
  "decompose": true,
  "rationale": "one sentence why",
  "subtasks": [
    {{
      "id": "<parent_id>.st<N>",
      "title": "...",
      "owner": "claude-code | codex-cli | gemini-cli | opencode",
      "tier": "mini | standard | max",
      "effort": "low | medium | high | xhigh",
      "blocked_by": "<parent_id>.st<N-1>" | null,
      "estimated_tokens": <int>
    }}
  ]
}}

When decompose is false, return empty subtasks array.
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


@dataclass
class RoutingPlan:
    """Full routing decision: owner + tier + effort + decomposition."""
    owner: str
    tier: str
    effort: str
    decompose: bool
    rationale: str = ""
    subtasks: list[dict[str, Any]] = field(default_factory=list)
    total_estimated_cost_usd: float = 0.0
    recommended_budget_usd: float = 0.0


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

    def route(self, task: dict[str, Any]) -> RoutingPlan:
        """Full routing decision: owner + tier + effort + decomposition.

        Calls the orchestrator model to decide WHO executes the task,
        at WHAT tier, with WHAT effort, and whether to split into subtasks.
        Falls back to standard dispatch on failure.
        """
        prompt = self._build_decompose_prompt(task)
        raw = self._call_orchestrator_model(prompt)

        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            logger.warning("Orchestrator returned invalid JSON, using fallback")
            return self._fallback_routing(task)

        if not isinstance(data, dict):
            return self._fallback_routing(task)

        owner = str(data.get("owner") or "claude-code")
        tier = str(data.get("tier") or "standard")
        effort = str(data.get("effort") or "medium")
        decompose = bool(data.get("decompose", False))
        rationale = str(data.get("rationale") or "")
        raw_subtasks = data.get("subtasks") or []

        subtasks: list[dict[str, Any]] = []
        if decompose and isinstance(raw_subtasks, list):
            for st in raw_subtasks:
                if isinstance(st, dict):
                    st_owner = st.get("owner", owner)
                    st_tier = st.get("tier", tier)
                    st_effort = st.get("effort", effort)
                    subtasks.append({
                        "id": str(st.get("id", f"{task.get('id', 'task')}.st{len(subtasks)+1}")),
                        "title": str(st.get("title", "subtask")),
                        "owner": st_owner,
                        "model_tier": st_tier,
                        "effort": st_effort,
                        "blocked_by": st.get("blocked_by"),
                        "estimated_tokens": int(st.get("estimated_tokens", 0)),
                    })

        # Enrich with cost estimates
        if subtasks:
            cost_input = [
                {"model_tier": st["model_tier"], "estimated_tokens": st["estimated_tokens"]}
                for st in subtasks
            ]
            task_estimate = estimate_task_cost(cost_input)
            total_cost = task_estimate.total_estimated_cost_usd
            budget = task_estimate.recommended_budget_usd
        else:
            total_cost = 0.0
            budget = 0.0

        return RoutingPlan(
            owner=owner,
            tier=tier,
            effort=effort,
            decompose=decompose,
            rationale=rationale,
            subtasks=subtasks,
            total_estimated_cost_usd=total_cost,
            recommended_budget_usd=budget,
        )

    def _fallback_routing(self, task: dict[str, Any]) -> RoutingPlan:
        """Fallback routing when orchestrator fails."""
        return RoutingPlan(
            owner=task.get("owner", "claude-code"),
            tier="standard",
            effort="medium",
            decompose=False,
            rationale="Orchestrator unavailable — using standard dispatch",
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
        _log_orchestrator_error("all models failed for decomposition")
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
