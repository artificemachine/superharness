"""Role-based model routing for multi-agent dispatch.

Maps orchestrator / worker / validator roles to model presets.
Reads project overrides from .superharness/profile.yaml under
the `model_routing` key. Falls back to hardcoded defaults.

Default routing rationale (from Factory Missions analysis):
- orchestrator: slow + deep reasoning → Opus
- worker: fast + code fluency → Sonnet
- validator: precise instruction following → Sonnet
"""
from __future__ import annotations

import os
from typing import Any

import logging
logger = logging.getLogger(__name__)

_DEFAULT_ROUTING: dict[str, str] = {
    "orchestrator": "claude-opus-4-6",
    "worker": "claude-sonnet-4-6",
    "validator": "claude-sonnet-4-6",
    "code_reviewer": "claude-sonnet-4-6",
}


class ModelRouter:
    """Resolve model name from role, with per-project profile overrides."""

    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self._overrides = overrides or {}

    @classmethod
    def from_project(cls, project_dir: str) -> "ModelRouter":
        """Load routing overrides from .superharness/profile.yaml."""
        profile_path = os.path.join(project_dir, ".superharness", "profile.yaml")
        try:
            import yaml  # type: ignore[import]
            with open(profile_path) as f:
                profile: dict[str, Any] = yaml.safe_load(f) or {}
            overrides = profile.get("model_routing") or {}
            return cls(overrides=overrides)
        except Exception as e:
            logger.warning("model_router_roles.py unexpected error: %s", e, exc_info=True)
            return cls()

    def model_for(self, role: str) -> str:
        """Return the resolved model name for the given role."""
        return self._overrides.get(role) or _DEFAULT_ROUTING.get(role) or "claude-sonnet-4-6"

    def all_routes(self) -> dict[str, str]:
        """Return effective routing table (defaults merged with overrides)."""
        merged = {**_DEFAULT_ROUTING, **self._overrides}
        return merged
