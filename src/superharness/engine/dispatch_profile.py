"""Dispatch profiles: role-specific worktree policy and payload filtering.

Three built-in profiles (orchestrator, worker, validator) determine:
- Whether a fresh worktree is required
- Which fields are included in the dispatch payload
- Whether context inheritance from the previous agent is allowed
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_ROLE_PROFILES: dict[str, dict[str, Any]] = {
    "orchestrator": {
        "fresh_worktree": False,
        "inherit_context": True,
        "payload_filter": None,  # full payload
    },
    "worker": {
        "fresh_worktree": False,
        "inherit_context": True,
        "payload_filter": None,  # full payload
    },
    "validator": {
        # Validators must never see the worker's session context.
        # They receive only: locked contract, diff since plan_approved,
        # and the report handoff. No worker logs, no worker context window.
        "fresh_worktree": True,
        "inherit_context": False,
        "payload_filter": {"locked_contract", "diff_since_plan_approved", "handoff_report"},
    },
    "code_reviewer": {
        "fresh_worktree": True,
        "inherit_context": False,
        "payload_filter": {"locked_contract", "diff_since_plan_approved"},
    },
}

_DEFAULT_ROLE = "worker"


@dataclass(frozen=True)
class DispatchProfile:
    role: str
    fresh_worktree: bool
    inherit_context: bool
    payload_filter: frozenset[str] | None  # None = no filtering

    @classmethod
    def for_role(cls, role: str) -> "DispatchProfile":
        cfg = _ROLE_PROFILES.get(role, _ROLE_PROFILES[_DEFAULT_ROLE])
        pf = cfg["payload_filter"]
        return cls(
            role=role,
            fresh_worktree=cfg["fresh_worktree"],
            inherit_context=cfg["inherit_context"],
            payload_filter=frozenset(pf) if pf is not None else None,
        )

    def filter_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return payload with only the fields allowed for this profile."""
        if self.payload_filter is None:
            return payload
        return {k: v for k, v in payload.items() if k in self.payload_filter}

    def build_review_payload(
        self,
        locked_contract: str | None,
        diff: str,
        handoff_report: str | None,
    ) -> dict[str, Any]:
        """Build the minimal payload for a validator/code_reviewer dispatch."""
        raw: dict[str, Any] = {
            "locked_contract": json.loads(locked_contract) if locked_contract else None,
            "diff_since_plan_approved": diff,
            "handoff_report": handoff_report,
        }
        return self.filter_payload(raw)
