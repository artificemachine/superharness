"""Automatic model routing for task delegation.

Classifies tasks into (tier, effort) using Haiku, then maps to agent-specific
model names. Falls back to ("standard", "medium") on any failure.
"""
from __future__ import annotations

import subprocess

from superharness.engine.taxonomy import VALID_EFFORTS

MODEL_MAP: dict[str, dict[str, str]] = {
    "claude-code": {
        "mini": "claude-haiku-4-5-20251001",
        "standard": "claude-sonnet-4-6",
        "max": "claude-opus-4-7"
    },
    "codex-cli": {
        "mini": "gpt-5.1-codex-mini",
        "standard": "gpt-5.3-codex",
        "max": "gpt-5.4"
    },
    "gemini-cli": {
        "mini": "gemini-2.0-flash",
        "standard": "gemini-2.0-pro",
        "max": "gemini-ultra"
    },
}

VALID_TIERS = {"mini", "standard", "max"}

_FALLBACK_TIER = "standard"
_FALLBACK_EFFORT = "medium"

_CLASSIFY_PROMPT = """\
You are a model router. Given a task, reply with exactly two words: <tier> <effort>

Tiers:
- mini: docs, README, changelog, config, env vars, single-file boilerplate, field additions, schema updates, no multi-step reasoning
- standard: multi-file coding, refactoring, debugging, tests, feature implementation, API integration, anything not clearly mini or max
- max: architecture design, cross-system migration, security audit, task failed 2+ times, 5+ interdependent constraints

Effort:
- low: task is well-defined, bounded scope, little ambiguity, expected output is short
- medium: typical coding task, some judgment needed, moderate scope
- high: complex reasoning, multiple constraints, subtle edge cases, concurrency, cross-system tradeoffs

Task:
  Title: {title}
  Acceptance criteria: {criteria}
  Files: {files}
  Previously failed: {failed}

Reply:"""


def classify_task(
    title: str,
    criteria: list[str] | None = None,
    files: list[str] | None = None,
    previously_failed: bool = False,
) -> tuple[str, str]:
    """Ask Haiku which tier and effort should handle this task.

    Returns (tier, effort). Defaults to ('standard', 'medium') on any failure.
    """
    criteria_str = ", ".join(criteria) if criteria else "none"
    files_str = ", ".join(files) if files else "none"
    failed_str = "yes" if previously_failed else "no"

    prompt = _CLASSIFY_PROMPT.format(
        title=title,
        criteria=criteria_str,
        files=files_str,
        failed=failed_str,
    )

    try:
        result = subprocess.run(
            ["claude", "--model", "haiku", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return _FALLBACK_TIER, _FALLBACK_EFFORT

        parts = result.stdout.strip().lower().split()
        if len(parts) < 2:
            return _FALLBACK_TIER, _FALLBACK_EFFORT

        tier = parts[0] if parts[0] in VALID_TIERS else _FALLBACK_TIER
        effort = parts[1] if parts[1] in VALID_EFFORTS else _FALLBACK_EFFORT
        return tier, effort

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return _FALLBACK_TIER, _FALLBACK_EFFORT


def resolve_model(target: str, tier: str) -> str:
    """Map a tier to the agent's actual model name via the adapter registry."""
    from superharness.engine.adapter_registry import resolve_model as _resolve
    res = _resolve(target, tier)
    return res["id"]


def resolve_tier(model_name: str) -> str | None:
    """If model_name is a tier name (mini/standard/max), return it. Otherwise None."""
    if model_name in VALID_TIERS:
        return model_name
    return None
