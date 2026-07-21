"""Routing-strategy resolution — who owns the model decision for a project.

THE polarity contract (2026-07-10): **RMDI prevails by default.** The
superharness-native model ladder is an EPHEMERAL, session-scoped opt-out,
triggered by an environment variable that dies with the shell — never by
editing a durable file:

    resolution order:  SUPERHARNESS_ROUTING_STRATEGY env  >  profile.yaml  >  "rmdi"

- `SUPERHARNESS_ROUTING_STRATEGY=native shux delegate ...` — this session
  (or this one command) uses the native ladder; nothing persists.
- `.superharness/profile.yaml: routing_strategy: native` — a deliberate,
  durable per-project choice (legit for projects with no router).
- Nothing set — the RMDI router is the model authority, fail-loud when down.

A swallowed profile-read error therefore lands on "rmdi" — the safe
direction: model authority stays with the router and a down router fails
loud, instead of silently handing the decision back to the shux ladder
(review finding 4).

This module is also the ONE home for profile reading on the routing path
(memoized on (path, mtime) — profile.yaml lives on NFS and was being parsed
5-9x per dispatch) and for role→seat mapping, so engine code never imports
from the commands layer.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

VALID_STRATEGIES = ("rmdi", "native")
DEFAULT_STRATEGY = "rmdi"
ENV_VAR = "SUPERHARNESS_ROUTING_STRATEGY"

# Role → seat defaults. Only entries that DIFFER from the f"{role}@shux"
# fallback carry information; the argparse --role choices are
# [orchestrator, worker, validator, code_reviewer].
DEFAULT_SEAT_MAP = {
    "validator": "reviewer@shux",
    "code_reviewer": "reviewer@shux",
}
# Binding endpoint (providerID) → superharness adapter. Endpoint identity is
# transport, not model semantics — no model name enters task state through this.
DEFAULT_ADAPTER_MAP = {
    "claude": "claude-code",
    "codex": "codex-cli",
    # pi is the canonical harness for everything else (fleet/local models);
    # OpenCode was decommissioned 2026-07-07 — RMDI refs are pi-native.
    "*": "pi",
}

_profile_cache: dict[str, tuple[float, dict]] = {}


def load_profile(project_dir: str) -> dict:
    """Parse .superharness/profile.yaml, memoized on file mtime."""
    path = os.path.join(project_dir, ".superharness", "profile.yaml")
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        return {}
    cached = _profile_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        import yaml

        with open(path) as f:
            doc = yaml.safe_load(f) or {}
        if not isinstance(doc, dict):
            doc = {}
    except Exception as e:
        logger.warning("routing.py profile read failed (%s): %s", path, e, exc_info=True)
        return {}
    _profile_cache[path] = (mtime, doc)
    return doc


def resolve_routing_strategy(project_dir: str) -> str:
    """env > profile > default 'rmdi'. Unknown values fall to the default
    LOUDLY (stderr-visible via lastResort logging) — never silently."""
    env = os.environ.get(ENV_VAR, "").strip().lower()
    if env in VALID_STRATEGIES:
        return env
    if env:
        logger.warning("%s=%r is not one of %s — ignoring", ENV_VAR, env, VALID_STRATEGIES)
    profile = load_profile(project_dir).get("routing_strategy")
    if isinstance(profile, str) and profile.strip().lower() in VALID_STRATEGIES:
        return profile.strip().lower()
    if profile is not None:
        logger.warning("profile routing_strategy=%r is not one of %s — using %s", profile, VALID_STRATEGIES, DEFAULT_STRATEGY)
    return DEFAULT_STRATEGY


def rmdi_config(project_dir: str) -> dict[str, Any]:
    """The profile's `rmdi:` block ({} when absent)."""
    val = load_profile(project_dir).get("rmdi")
    return dict(val) if isinstance(val, dict) else {}


def seat_for(role: str, cfg: dict[str, Any] | None = None) -> str:
    """Map a delegation role to its RMDI seat: profile seat_map > defaults >
    f'{role}@shux'. The single source for BOTH delegate and orchestrator."""
    seat_map = {**DEFAULT_SEAT_MAP, **((cfg or {}).get("seat_map") or {})}
    return seat_map.get(role) or f"{role}@shux"


def adapter_for(provider_id: str, cfg: dict[str, Any] | None = None) -> str:
    adapter_map = {**DEFAULT_ADAPTER_MAP, **((cfg or {}).get("adapter_map") or {})}
    return adapter_map.get(provider_id) or adapter_map.get("*", "pi")
