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
        "max": "claude-opus-4-8"
    },
    "codex-cli": {
        "mini": "gpt-5.1-codex-mini",
        "standard": "gpt-5.3-codex",
        "max": "gpt-5.4"
    },
    "gemini-cli": {
        "mini": "gemini-2.5-flash",
        "standard": "gemini-2.5-pro",
        "max": "gemini-3.1-pro-preview"
    },
    "opencode": {
        "mini": "deepseek/deepseek-chat",
        "standard": "deepseek/deepseek-v4-pro",
        "max": "deepseek/deepseek-v4-pro"
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


# Classifier chain: agents tried in order for task/discussion classification.
# Each agent is queried with its mini-tier model. First to respond wins.
# If all agents fail (down, timeout, not installed), falls back to standard.
# Order: cheapest first, then by reliability.
_CLASSIFIER_AGENTS: list[tuple[str, list[str]]] = [
    ("claude-code", ["claude", "--model", "{model}", "-p", "{prompt}"]),
    ("gemini-cli",  ["gemini", "-m", "{model}", "-p", "{prompt}"]),
    ("opencode",    ["opencode", "run", "-m", "{model}", "{prompt}"]),
    ("codex-cli",   ["codex", "exec", "-m", "{model}", "{prompt}"]),
]

_CLASSIFY_TIMEOUT_SECONDS = 5


def _try_classify(agent: str, cmd_template: list[str], model: str, prompt: str) -> tuple[str, str] | None:
    """Try classification with one agent's mini model. Returns (tier, effort) or None."""
    cmd = [part.format(model=model, prompt=prompt) for part in cmd_template]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_CLASSIFY_TIMEOUT_SECONDS, check=False,
        )
        if result.returncode != 0:
            return None
        parts = result.stdout.strip().lower().split()
        if len(parts) < 2:
            return None
        tier = parts[0] if parts[0] in VALID_TIERS else _FALLBACK_TIER
        effort = parts[1] if parts[1] in VALID_EFFORTS else _FALLBACK_EFFORT
        return tier, effort
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def classify_task(
    title: str,
    criteria: list[str] | None = None,
    files: list[str] | None = None,
    previously_failed: bool = False,
    project_dir: str | None = None,
) -> tuple[str, str]:
    """Ask the classifier chain which tier and effort should handle this task.

    Tries each agent's mini model in order. First to respond wins.
    Returns (tier, effort). Defaults to ('standard', 'medium') on any failure.
    """
    mmap = _load_model_map(project_dir)
    criteria_str = ", ".join(criteria) if criteria else "none"
    files_str = ", ".join(files) if files else "none"
    failed_str = "yes" if previously_failed else "no"

    prompt = _CLASSIFY_PROMPT.format(
        title=title,
        criteria=criteria_str,
        files=files_str,
        failed=failed_str,
    )

    for agent_name, cmd_template in _CLASSIFIER_AGENTS:
        agent_map = mmap.get(agent_name, {})
        model = agent_map.get("mini", "")
        if not model:
            continue
        result = _try_classify(agent_name, cmd_template, model, prompt)
        if result is not None:
            return result

    return _FALLBACK_TIER, _FALLBACK_EFFORT


_CODEX_AUTH_MODE_CACHE: str | None = None


def detect_codex_auth_mode() -> str:
    """Return codex auth mode: 'chatgpt' | 'apikey' | 'unknown'.

    Codex CLI exposes this via `codex login status`. ChatGPT-account auth
    rejects API-only models (e.g. observed: gpt-5.3-codex) with HTTP 400.
    Memoized at module level — auth state doesn't change mid-process and
    the subprocess takes ~1s.

    Note: do not read ~/.codex directly (CLAUDE.md rule 11). Shelling out
    to the codex binary is the supported entry point.
    """
    global _CODEX_AUTH_MODE_CACHE
    if _CODEX_AUTH_MODE_CACHE is not None:
        return _CODEX_AUTH_MODE_CACHE
    try:
        r = subprocess.run(
            ["codex", "login", "status"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        out = (r.stdout + " " + r.stderr).lower()
        if "chatgpt" in out:
            _CODEX_AUTH_MODE_CACHE = "chatgpt"
        elif "api key" in out or "api-key" in out or "apikey" in out:
            _CODEX_AUTH_MODE_CACHE = "apikey"
        else:
            _CODEX_AUTH_MODE_CACHE = "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        _CODEX_AUTH_MODE_CACHE = "unknown"
    return _CODEX_AUTH_MODE_CACHE


def _reset_codex_auth_cache() -> None:
    """Test-only hook to clear the auth-mode memoization."""
    global _CODEX_AUTH_MODE_CACHE
    _CODEX_AUTH_MODE_CACHE = None


def _apply_chatgpt_auth_override(target: str, model: str, project_dir: str | None) -> str:
    """If target is codex-cli on chatgpt-account auth and the model has a
    project-configured override for ChatGPT auth, swap to the override.

    The override map lives at models.yaml under `chatgpt_account_overrides:`.
    Empty by default — populate when a stable incompatibility is observed.
    Example:
        chatgpt_account_overrides:
          gpt-5.3-codex: gpt-5-codex   # API-only model → ChatGPT-compatible fallback
    """
    if target != "codex-cli":
        return model
    config = load_yaml_config(
        bundled_pkg="superharness",
        bundled_filename="engine/models.yaml",
        project_dir=project_dir,
        project_filename="models.yaml",
        fallback={},
    )
    overrides = config.get("chatgpt_account_overrides") or {}
    if not overrides or model not in overrides:
        return model
    if detect_codex_auth_mode() != "chatgpt":
        return model
    return overrides[model]


def resolve_model(target: str, tier: str, project_dir: str | None = None) -> str:
    """Map a tier to the agent's actual model name via YAML config or adapter registry.

    1. Check _load_model_map (bundled or project override).
    2. Fall back to adapter registry.
    3. Fall back to MODEL_MAP then sonnet.
    4. For codex-cli: apply chatgpt_account_overrides if user is on ChatGPT auth.
    """
    mmap = _load_model_map(project_dir)
    if target in mmap and tier in mmap[target]:
        return _apply_chatgpt_auth_override(target, mmap[target][tier], project_dir)

    from superharness.engine.adapter_registry import resolve_model as _resolve
    res = _resolve(target, tier)
    model_id = res.get("id", "")
    if not model_id or model_id == tier:
        fallback = mmap.get(target, {}).get(tier, MODEL_MAP.get(target, {}).get(tier, "claude-sonnet-4-6"))
        return _apply_chatgpt_auth_override(target, fallback, project_dir)
    return _apply_chatgpt_auth_override(target, model_id, project_dir)


def resolve_tier(model_name: str) -> str | None:
    """If model_name is a tier name (mini/standard/max), return it. Otherwise None."""
    if model_name in VALID_TIERS:
        return model_name
    return None


def find_tier_for_model(target: str, model_name: str, project_dir: str | None = None) -> str:
    """Reverse lookup: find the tier name (mini/standard/max) for a given model ID.
    
    Checks project-specific map first, then defaults.
    """
    mmap = _load_model_map(project_dir)
    target_map = mmap.get(target, {})
    for tier, m_id in target_map.items():
        if m_id == model_name:
            return tier
            
    # Fallback to default MODEL_MAP
    target_map = MODEL_MAP.get(target, {})
    for tier, m_id in target_map.items():
        if m_id == model_name:
            return tier
            
    # If the model_name itself is a tier, return it
    if model_name in VALID_TIERS:
        return model_name
        
    return _FALLBACK_TIER


def classify_complexity(task: dict) -> str:
    """Classify task complexity: simple, medium, or complex.

    Heuristics cherry-picked from hermes-agent/agent/smart_model_routing.py.
    """
    title = str(task.get("title", task.get("id", "")))
    criteria = task.get("acceptance_criteria") or []
    ac_count = len([c for c in criteria if str(c).strip()])
    effort = str(task.get("effort", "medium")).lower()
    context = str(task.get("context", "")).lower()

    # High complexity signals
    complex_signals = [
        "refactor", "migrate", "redesign", "architecture",
        "security", "auth", "api", "database", "schema",
        "multi-file", "breaking change", "cross-cutting",
        "performance", "optimize", "scale",
    ]
    # Simple task signals
    simple_signals = ["typo", "fix comment", "rename", "update readme",
                      "add test", "config", "bump version", "changelog"]

    is_complex = (
        effort in ("xhigh", "max")
        or ac_count > 3
        or any(s in title.lower() or s in context for s in complex_signals)
    )

    if is_complex:
        return "complex"

    is_simple = (
        effort == "low"
        or ac_count == 0
        or any(s in (title.lower() + context) for s in simple_signals)
    )

    return "simple" if is_simple else "medium"


def suggest_tier(complexity: str, budget_remaining: float | None = None) -> str:
    """Suggest model tier based on complexity and budget.

    Returns: mini, standard, or max.
    """
    if complexity == "complex":
        return "max"
    if complexity == "simple":
        if budget_remaining is not None and budget_remaining < 1.0:
            return "mini"
        return "mini"
    # medium
    if budget_remaining is not None and budget_remaining < 3.0:
        return "mini"
    return "standard"


# Per-agent tier routing for discussions.
# When the discussion topic tier is high, not all agents need max compute.
# Primary reasoners (claude, opencode) get the full tier; secondary agents
# (gemini, codex) are capped at standard for cost efficiency.
_DISCUSSION_TIER_ROUTING: dict[str, dict[str, str]] = {
    "max": {
        "claude-code": "max",
        "opencode": "max",
        "gemini-cli": "standard",
        "codex-cli": "standard",
    },
    "standard": {
        "claude-code": "standard",
        "opencode": "standard",
        "gemini-cli": "standard",
        "codex-cli": "standard",
    },
    "mini": {
        "claude-code": "mini",
        "opencode": "mini",
        "gemini-cli": "mini",
        "codex-cli": "mini",
    },
}


def route_discussion_tier(topic_tier: str, agent: str) -> str:
    """Route a discussion topic tier to a per-agent tier.

    For max-tier discussions, primary reasoners get max while secondary
    agents are capped at standard. For standard and mini, everyone gets
    the same tier. Unknown agents get the topic tier unchanged.
    """
    tier_map = _DISCUSSION_TIER_ROUTING.get(topic_tier, {})
    return tier_map.get(agent, topic_tier)
