"""Automatic model routing for task delegation.

Classifies tasks into (tier, effort) using Haiku, then maps to agent-specific
model names. Falls back to ("standard", "medium") on any failure.
"""
from __future__ import annotations

import os
import subprocess

from superharness.engine.taxonomy import VALID_EFFORTS
from superharness.engine.config_loader import load_yaml_config
from superharness.engine.adapter_registry import flagship

MODEL_MAP: dict[str, dict[str, str]] = {
    "claude-code": {
        "mini": "claude-haiku-4-5-20251001",
        "standard": "claude-sonnet-4-6",
        "max": flagship()
    },
    "codex-cli": {
        "mini": "gpt-5.1-codex-mini",
        "standard": "gpt-5.3-codex",
        "max": "gpt-5.4"
    },
    "gemini-cli": {
        "mini": "gemini-2.5-flash",
        "standard": "gemini-2.5-pro",
        "max": "gemini-2.5-pro"
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

# Normalization map: ensure consistent output regardless of which model responds.
# Some models output "max" others "maximum", some "small" others "mini", etc.
_TIER_NORMALIZE: dict[str, str] = {
    "maximum": "max", "large": "max", "heavy": "max", "opus": "max",
    "medium": "standard", "normal": "standard", "mid": "standard",
    "small": "mini", "light": "mini", "fast": "mini", "haiku": "mini",
    "tiny": "mini",
}
_EFFORT_NORMALIZE: dict[str, str] = {
    "high": "high", "hard": "high", "complex": "high",
    "medium": "medium", "normal": "medium", "mid": "medium",
    "low": "low", "easy": "low", "simple": "low", "trivial": "low",
}


def cheap_model(agent: str = "claude-code") -> str:
    """Return the cheap (mini) tier model for an agent.

    Used by batch / non-interactive callers (e.g. memory distillation) that
    want the lowest-cost model without running the full classifier chain.
    """
    return MODEL_MAP.get(agent, MODEL_MAP["claude-code"])["mini"]


def _normalize_classification(tier: str, effort: str) -> tuple[str, str]:
    """Normalize classification output for consistent behavior across models."""
    tier = _TIER_NORMALIZE.get(tier.lower(), tier.lower())
    effort = _EFFORT_NORMALIZE.get(effort.lower(), effort.lower())
    if tier not in VALID_TIERS:
        tier = _FALLBACK_TIER
    if effort not in VALID_EFFORTS:
        effort = _FALLBACK_EFFORT
    return tier, effort


def _deterministic_classify(title: str, criteria: list[str] | None, previously_failed: bool) -> tuple[str, str]:
    """Deterministic heuristic classification — always produces the same output.
    
    Used when all models are unavailable. Never fails, never varies.
    """
    if previously_failed:
        return "max", "high"
    
    title_lower = title.lower()
    criteria_text = " ".join(criteria).lower() if criteria else ""
    combined = title_lower + " " + criteria_text
    
    # max-tier signals
    max_signals = [
        "architecture", "migration", "security audit", "breaking change",
        "cross-system", "multi-service", "10+ files", "database schema",
        "auth", "performance critical", "concurrency", "race condition",
    ]
    if any(s in combined for s in max_signals):
        return "max", "high"
    
    # mini-tier signals
    mini_signals = [
        "readme", "changelog", "typo", "comment", "config", "env var",
        "single file", "one-line", "field name", "rename",
    ]
    if any(s in combined for s in mini_signals):
        return "mini", "low"
    
    # default
    return _FALLBACK_TIER, _FALLBACK_EFFORT

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

    # Merge user fleet config if present (~/.config/superharness/fleet.yaml).
    # Fleet endpoints are local GPU VMs that superharness ITSELF uses for
    # internal AI operations (task classification, routing decisions, etc.).
    # Agents keep their own model tiers unchanged — the fleet is the harness's
    # brain, not the agents' provider.
    fleet = _load_fleet_config()
    if fleet:
        _FLEET_CACHE = fleet

    if project_dir is None:
        _cached_map = mmap
    else:
        _cached_project_maps[project_dir] = mmap
    return mmap


_FLEET_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".config", "superharness", "fleet.yaml")
_FLEET_CACHE: dict | None = None


def _load_fleet_config() -> dict | None:
    """Load user-specific fleet configuration if it exists.
    
    Returns dict with 'endpoints' and 'models' keys, or None if no fleet config.
    Cached after first load.
    """
    global _FLEET_CACHE
    if _FLEET_CACHE is not None:
        return _FLEET_CACHE
    if not os.path.isfile(_FLEET_CONFIG_PATH):
        _FLEET_CACHE = None
        return None
    try:
        import yaml
        with open(_FLEET_CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}
        fleet = config.get("fleet", {})
        if fleet:
            _FLEET_CACHE = fleet
            return fleet
    except Exception:
        pass
    _FLEET_CACHE = None
    return None


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


def fleet_health(timeout: float = 3.0) -> list[tuple[str, str, str]]:
    """Check each configured fleet tier against its endpoint's /models list.

    Returns one (tier, model, status) row per configured tier, status in
    {"ok", "endpoint-unreachable", "model-missing"}. Empty list if no fleet
    is configured. Never raises.
    """
    fleet = _load_fleet_config()
    if not fleet:
        return []
    endpoints = fleet.get("endpoints", {})
    models = fleet.get("models", {})
    results: list[tuple[str, str, str]] = []
    for tier, model in models.items():
        endpoint = endpoints.get(tier) or endpoints.get("all")
        if not endpoint or not model:
            continue
        try:
            import urllib.request
            import json as _json
            req = urllib.request.Request(f"{endpoint.rstrip('/')}/models")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = _json.loads(resp.read())
                available = {m.get("id") for m in data.get("data", [])}
            status = "ok" if model in available else "model-missing"
        except Exception:
            status = "endpoint-unreachable"
        results.append((tier, model, status))
    return results


def _fleet_candidates(fleet: dict) -> list[tuple[str, str]]:
    """Return ordered, deduplicated (endpoint, model) pairs for a fleet config.

    Each tier's endpoint is paired with that SAME tier's model (falling back
    to the "all" model when the tier has no model of its own) — unlike the
    old precedence chain, which could pick tier N's endpoint but tier M's
    model if they didn't line up. Order: mini, standard, all.
    """
    endpoints = fleet.get("endpoints", {})
    models = fleet.get("models", {})
    fallback_model = models.get("all")
    candidates: list[tuple[str, str]] = []
    for tier in ("mini", "standard", "all"):
        endpoint = endpoints.get(tier)
        model = models.get(tier) or fallback_model
        if not endpoint or not model:
            continue
        pair = (endpoint, model)
        if pair not in candidates:
            candidates.append(pair)
    return candidates


def _call_fleet(prompt: str, expect_tokens: int = 10) -> str | None:
    """Call the fleet API and return the response text. Tries every configured
    endpoint in tier order (mini, standard, all) until one succeeds. Returns
    None if none respond."""
    fleet = _load_fleet_config()
    if not fleet:
        return None
    for endpoint, model_id in _fleet_candidates(fleet):
        result = _call_fleet_endpoint(endpoint, model_id, prompt, expect_tokens)
        if result is not None:
            return result
    return None


def _call_fleet_endpoint(endpoint: str, model_id: str, prompt: str, expect_tokens: int) -> str | None:
    """Call one fleet endpoint. Returns None on any failure."""
    try:
        import urllib.request
        import json as _json
        payload = _json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": expect_tokens,
            "temperature": 0,
        }).encode()
        req = urllib.request.Request(
            f"{endpoint.rstrip('/')}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = _json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _classify_via_fleet(prompt: str) -> tuple[str, str] | None:
    """Try task classification using the local GPU fleet (OpenAI-compatible API).
    
    Returns (tier, effort) or None if fleet unavailable. This is superharness's
    own brain — no external agent CLI needed, no API key, no latency to cloud.
    """
    response = _call_fleet(prompt, expect_tokens=2)
    if response:
        parts = response.lower().split()
        if len(parts) >= 2:
            tier = parts[0] if parts[0] in VALID_TIERS else _FALLBACK_TIER
            effort = parts[1] if parts[1] in VALID_EFFORTS else _FALLBACK_EFFORT
            return tier, effort
    return None


_FAILURE_ANALYSIS_PROMPT = """\
You are superharness's diagnostic brain. Analyze this agent failure and reply with EXACTLY ONE classification word or phrase from the list below.

Agent: {agent}
Task: {task}
Error: {error}
Recent failures for this agent: {history}

Classifications (pick ONE):
- transient: temporary issue, retry with backoff
- permanent_block: agent is misconfigured or broken, pause it
- config: fixable configuration issue
- dependency: missing module or binary
- timeout: agent took too long
- unknown: cannot determine cause

Reply with exactly one word or phrase (transient, permanent_block, config, dependency, timeout, or unknown):"""


def analyze_failure(agent: str, task: str, error: str, history: str = "") -> str:
    """Use the fleet to analyze an agent failure and determine root cause.
    
    Returns one of: transient, permanent_block, config, dependency, timeout, unknown.
    Falls back to 'unknown' if fleet unavailable.
    """
    prompt = _FAILURE_ANALYSIS_PROMPT.format(
        agent=agent,
        task=task[:200],
        error=error[:500],
        history=history[:300] or "none",
    )
    response = _call_fleet(prompt, expect_tokens=5)
    if response:
        response = response.strip().lower()
        valid = {"transient", "permanent_block", "config", "dependency", "timeout", "unknown"}
        # Extract the first valid classification word
        for word in response.split():
            word = word.strip(".,;:")
            if word in valid:
                return word
    return "unknown"


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

    Classification chain (best-model-first, consistent fallbacks):
      1. Fleet (local GPU) — fastest, no cloud cost
      2. Cloud models via agent CLIs — always available, higher quality
      3. Deterministic heuristic — never fails, consistent behavior

    All outputs are normalized to ensure identical behavior regardless
    of which model in the chain responds.
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

    # 1. Fleet first — superharness's own brain (local GPU, fastest)
    result = _classify_via_fleet(prompt)
    if result is not None:
        return _normalize_classification(*result)

    # 2. Agent CLIs — cloud models, best quality fallback
    for agent_name, cmd_template in _CLASSIFIER_AGENTS:
        agent_map = mmap.get(agent_name, {})
        model = agent_map.get("mini", "")
        if not model:
            continue
        result = _try_classify(agent_name, cmd_template, model, prompt)
        if result is not None:
            return _normalize_classification(*result)

    # 3. Deterministic fallback — always consistent
    return _deterministic_classify(title, criteria, previously_failed)


_CODEX_AUTH_MODE_CACHE: str | None = None

# File written to .superharness/ so auth state survives across processes
# and can be read by the dashboard to surface "⚠ auth changed" warnings.
_AUTH_STATE_FILENAME = "agent-auth-state.json"


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


def reset_codex_auth_cache() -> None:
    """Invalidate the in-process auth-mode cache so the next call re-detects.

    Called by the dispatch failure handler when an auth_mismatch failure is
    observed (e.g. the operator switched ChatGPT accounts between sessions).
    The next dispatch will re-run `codex login status` and pick up the new
    account type, applying the correct chatgpt_account_overrides if needed.
    """
    global _CODEX_AUTH_MODE_CACHE
    _CODEX_AUTH_MODE_CACHE = None


# Keep the private alias so existing tests that import _reset_codex_auth_cache
# continue to work without modification.
_reset_codex_auth_cache = reset_codex_auth_cache


def persist_agent_auth_state(project_dir: str, agent: str, auth_mode: str) -> None:
    """Write detected auth mode for an agent to .superharness/agent-auth-state.json.

    Survives across process restarts; read by get_agent_auth_state() and the
    dashboard to surface auth-change warnings without re-running `codex login`.
    Preserves other fields (e.g. quota_limited_until) when updating auth_mode.
    """
    state = _load_agent_state(project_dir)
    agent_state = dict(state.get(agent) or {})
    agent_state["auth_mode"] = auth_mode
    state[agent] = agent_state
    _save_agent_state(project_dir, state)


def get_agent_auth_state(project_dir: str, agent: str) -> str | None:
    """Read the last-persisted auth mode for an agent, or None if not recorded."""
    import json
    from pathlib import Path
    path = Path(project_dir) / ".superharness" / _AUTH_STATE_FILENAME
    try:
        state = json.loads(path.read_text())
        return state.get(agent, {}).get("auth_mode")
    except Exception:
        return None


def _load_agent_state(project_dir: str) -> dict:
    """Read agent-auth-state.json and return the full dict (or empty on error)."""
    import json
    from pathlib import Path
    path = Path(project_dir) / ".superharness" / _AUTH_STATE_FILENAME
    try:
        if path.exists():
            return json.loads(path.read_text()) or {}
    except Exception:
        pass
    return {}


def _save_agent_state(project_dir: str, state: dict) -> None:
    """Write the full agent state dict back to disk. Best-effort."""
    import json
    from pathlib import Path
    path = Path(project_dir) / ".superharness" / _AUTH_STATE_FILENAME
    try:
        path.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def set_agent_quota_limited(project_dir: str, agent: str, reset_minutes: int = 60) -> None:
    """Record that an agent is quota-limited until now + reset_minutes.

    Written to agent-auth-state.json so the watcher can skip this agent
    in fallback routing without re-discovering the quota limit every time.
    Survives across process restarts.
    """
    from datetime import datetime, timezone, timedelta
    state = _load_agent_state(project_dir)
    agent_state = dict(state.get(agent) or {})
    expiry = datetime.now(timezone.utc) + timedelta(minutes=reset_minutes)
    agent_state["quota_limited_until"] = expiry.strftime("%Y-%m-%dT%H:%M:%SZ")
    state[agent] = agent_state
    _save_agent_state(project_dir, state)


def is_agent_quota_limited(project_dir: str, agent: str) -> bool:
    """Return True if the agent is currently within its quota cooldown window.

    Returns False if no quota state is recorded or if the cooldown has expired
    (so the watcher will attempt the agent again after the window passes).
    """
    from datetime import datetime, timezone
    state = _load_agent_state(project_dir)
    expiry_str = state.get(agent, {}).get("quota_limited_until")
    if not expiry_str:
        return False
    try:
        expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < expiry
    except Exception:
        return False


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
