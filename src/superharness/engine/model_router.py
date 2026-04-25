"""Automatic model routing for task delegation.

Classifies tasks into (tier, effort) using Haiku, then maps to agent-specific
model names. Falls back to ("standard", "medium") on any failure.
"""
from __future__ import annotations

import subprocess

from superharness.engine.taxonomy import VALID_EFFORTS
from superharness.engine.config_loader import load_yaml_config

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
        "mini": "flash",
        "standard": "pro",
        "max": "ultra"
    },
}

VALID_TIERS = {"mini", "standard", "max"}

_FALLBACK_TIER = "standard"
_FALLBACK_EFFORT = "medium"

_cached_map: dict[str, dict[str, str]] | None = None
_cached_project_maps: dict[str, dict[str, dict[str, str]]] = {}


def _load_model_map(project_dir: str | None = None) -> dict[str, dict[str, str]]:
    """Load model map from bundled YAML or project override."""
    global _cached_map, _cached_project_maps
    if project_dir is None:
        if _cached_map is not None:
            return _cached_map
    else:
        if project_dir in _cached_project_maps:
            return _cached_project_maps[project_dir]

    config = load_yaml_config(
        bundled_pkg="superharness",
        bundled_filename="engine/models.yaml",
        project_dir=project_dir,
        project_filename="models.yaml",
        fallback={"model_map": MODEL_MAP}
    )
    mmap = config.get("model_map", MODEL_MAP)

    if project_dir is None:
        _cached_map = mmap
    else:
        _cached_project_maps[project_dir] = mmap
    return mmap


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


def resolve_model(target: str, tier: str, project_dir: str | None = None) -> str:
    """Map a tier to the agent's actual model name via YAML config or adapter registry.

    1. Check _load_model_map (bundled or project override).
    2. Fall back to adapter registry.
    3. Fall back to MODEL_MAP then sonnet.
    """
    mmap = _load_model_map(project_dir)
    if target in mmap and tier in mmap[target]:
        return mmap[target][tier]

    from superharness.engine.adapter_registry import resolve_model as _resolve
    res = _resolve(target, tier)
    model_id = res.get("id", "")
    if not model_id or model_id == tier:
        return mmap.get(target, {}).get(tier, MODEL_MAP.get(target, {}).get(tier, "claude-sonnet-4-6"))
    return model_id


def resolve_tier(model_name: str) -> str | None:
    """If model_name is a tier name (mini/standard/max), return it. Otherwise None."""
    if model_name in VALID_TIERS:
        return model_name
    return None
