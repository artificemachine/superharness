"""Heuristic + LLM + safety floor classifier for task model routing.

§4.3-4.5 spec — three stages:
  Stage 1: heuristic_classify() — fast pattern matching, returns None on no match
  Stage 2: llm_classify()       — Sonnet subprocess fallback
  Stage 3: apply_safety_floor() — file count guard, budget guard, 1M auto-promote
  classify()                    — composes all three stages
"""
from __future__ import annotations

import subprocess
import warnings

from superharness.engine.adapter_registry import fallback_flagship, flagship, flagship_1m
from superharness.engine.taxonomy import EFFORT_ORDER, OPUS_KEYWORDS, VALID_EFFORTS

_FALLBACK_EFFORT = "medium"

_1M_TOKEN_THRESHOLD = 200_000

_LOW_TITLE_PREFIXES = ("fix.typo", "docs:", "chore:")

_FALLBACK_MODEL = "claude-sonnet-4-6"

# Module-level constants resolved from the manifest once at import time.
_FLAGSHIP = flagship()
_FLAGSHIP_1M = flagship_1m()
_FALLBACK = fallback_flagship()

def _is_opus_model(model_id: str) -> bool:
    """Return True if model_id is any Claude Opus variant (any generation)."""
    return model_id.startswith("claude-opus-")

_LLM_MODEL_MAP: dict[str, str] = {
    "sonnet-4-6": "claude-sonnet-4-6",
    "opus-4-6":   _FLAGSHIP,  # alias — route to latest flagship
    "opus-4-7":   _FALLBACK,  # version pin
    "opus-4-8":   _FLAGSHIP,
    "mini":       "claude-haiku-4-5-20251001",
    "standard":   "claude-sonnet-4-6",
    "max":        _FLAGSHIP,
}

_LLM_CLASSIFY_PROMPT = (
    "You are a model router. Decide which model+effort handles this task best.\n\n"
    "Models:\n"
    "- sonnet-4-6: multi-file coding, refactoring, debugging, tests, features, API integration\n"
    f"- {_FLAGSHIP}: 5+ interdependent constraints, cross-domain judgment, architecture, irreversible decisions, security review, compliance\n\n"
    "Effort: low | medium | high | xhigh | max\n"
    "(low=bounded; medium=typical; high=complex; xhigh=cross-system; max=highest-stakes)\n\n"
    "Task:\n"
    "  Title: {title}\n"
    "  Acceptance criteria: {criteria}\n"
    "  Files: {files}\n"
    "  Test types: {test_types}\n"
    "  Out of scope: {out_of_scope}\n"
    "  Context: {context}\n"
    "  Previously failed: {failed}\n\n"
    "Reply with exactly: <model> <effort>\n"
    'Example: "sonnet-4-6 medium"'
)


def heuristic_classify(
    title: str,
    criteria: list[str] | None = None,
    files: list[str] | None = None,
    test_types: list[str] | None = None,
    retry_count: int = 0,
    previous_model: str | None = None,
) -> tuple[str, str] | None:
    """Stage 1: fast heuristic classifier.

    Returns (model_id, effort) or None when no rule fires.
    Priority order: retry escalation → max triggers → xhigh triggers → low/medium demotes.
    """
    criteria_count = len(criteria) if criteria else 0
    file_count = len(files) if files else 0
    test_types_set = set(test_types or [])
    title_lower = title.lower()

    # Retry escalation: any Opus failure → promote to max
    if retry_count > 0 and _is_opus_model(previous_model or ""):
        return (_FLAGSHIP, "max")

    # Hard max triggers
    if criteria_count > 5:
        return (_FLAGSHIP, "max")
    if file_count > 10:
        return (_FLAGSHIP, "max")
    if "security" in test_types_set and criteria_count > 3:
        return (_FLAGSHIP, "max")

    # xhigh trigger: OPUS_KEYWORDS in title
    for keyword in OPUS_KEYWORDS:
        if keyword in title_lower:
            return (_FLAGSHIP, "xhigh")

    # Low demote: trivial-title prefixes with few AC
    if any(title_lower.startswith(p) for p in _LOW_TITLE_PREFIXES) and criteria_count <= 2:
        return ("claude-sonnet-4-6", "low")

    # Medium demote: unit-only tests with few files
    if test_types == ["unit"] and file_count <= 2:
        return ("claude-sonnet-4-6", "medium")

    return None


def llm_classify(
    title: str,
    criteria: list[str] | None = None,
    files: list[str] | None = None,
    test_types: list[str] | None = None,
    out_of_scope: list[str] | None = None,
    context: str | None = None,
    previously_failed: bool = False,
) -> tuple[str, str]:
    """Stage 2: Sonnet LLM fallback classifier.

    Returns (model_id, effort). Defaults to (claude-sonnet-4-6, medium) on any failure.
    """
    prompt = _LLM_CLASSIFY_PROMPT.format(
        title=title,
        criteria=", ".join(criteria) if criteria else "none",
        files=", ".join(files) if files else "none",
        test_types=", ".join(test_types) if test_types else "none",
        out_of_scope=", ".join(out_of_scope) if out_of_scope else "none",
        context=context or "none",
        failed="yes" if previously_failed else "no",
    )

    try:
        result = subprocess.run(
            ["claude", "--model", "claude-sonnet-4-6", "-p", prompt, "--max-tokens", "20"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            return _FALLBACK_MODEL, _FALLBACK_EFFORT

        parts = result.stdout.strip().lower().split()
        if len(parts) < 2:
            return _FALLBACK_MODEL, _FALLBACK_EFFORT

        model = _LLM_MODEL_MAP.get(parts[0], _FALLBACK_MODEL)
        effort = parts[1] if parts[1] in VALID_EFFORTS else _FALLBACK_EFFORT
        return model, effort

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return _FALLBACK_MODEL, _FALLBACK_EFFORT


def apply_safety_floor(
    model: str,
    effort: str,
    files: list[str] | None = None,
    estimated_tokens: int = 0,
    budget_remaining: float | None = None,
    estimated_cost: float | None = None,
) -> tuple[str, str]:
    """Stage 3: safety floor adjustments.

    Returns (model_id, effort) with guardrail adjustments applied.
    """
    file_count = len(files) if files else 0
    effort_idx = EFFORT_ORDER.index(effort) if effort in EFFORT_ORDER else 1
    high_idx = EFFORT_ORDER.index("high")

    # File count guard: sonnet + >6 files → bump effort to at least "high"
    if file_count > 6 and model == "claude-sonnet-4-6" and effort_idx < high_idx:
        effort = "high"
        effort_idx = high_idx

    # Budget guard: downgrade one effort step when cost exceeds remaining
    if (budget_remaining is not None and estimated_cost is not None
            and estimated_cost > budget_remaining and effort_idx > 0):
        effort_idx -= 1
        effort = EFFORT_ORDER[effort_idx]
        warnings.warn(
            f"Estimated cost ${estimated_cost:.3f} exceeds budget_remaining "
            f"${budget_remaining:.3f}; downgraded effort to {effort}",
            stacklevel=2,
        )

    # 1M auto-promotion
    if effort == "max" and estimated_tokens > _1M_TOKEN_THRESHOLD:
        model = _FLAGSHIP_1M

    return model, effort


def classify(
    title: str,
    criteria: list[str] | None = None,
    files: list[str] | None = None,
    test_types: list[str] | None = None,
    out_of_scope: list[str] | None = None,
    context: str | None = None,
    retry_count: int = 0,
    previous_model: str | None = None,
    previously_failed: bool = False,
    estimated_tokens: int = 0,
    budget_remaining: float | None = None,
    estimated_cost: float | None = None,
) -> tuple[str, str]:
    """Full classifier: Stage 1 heuristic → Stage 2 LLM → Stage 3 safety floor."""
    result = heuristic_classify(
        title=title,
        criteria=criteria,
        files=files,
        test_types=test_types,
        retry_count=retry_count,
        previous_model=previous_model,
    )
    if result is None:
        result = llm_classify(
            title=title,
            criteria=criteria,
            files=files,
            test_types=test_types,
            out_of_scope=out_of_scope,
            context=context,
            previously_failed=previously_failed,
        )
    model, effort = result
    return apply_safety_floor(
        model=model,
        effort=effort,
        files=files,
        estimated_tokens=estimated_tokens,
        budget_remaining=budget_remaining,
        estimated_cost=estimated_cost,
    )
