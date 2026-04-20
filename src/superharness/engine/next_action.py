"""next_action — derive the recommended next move for a task.

Pure leaf module: no imports from other superharness engine modules.
Called by adapter_payload to populate next_action per task in schema v1.3.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Canonical status enum (all statuses the state machine recognises)
# ---------------------------------------------------------------------------

ALL_STATUSES: list[str] = [
    "todo",
    "plan_proposed",
    "plan_approved",
    "in_progress",
    "pending_user_approval",
    "report_ready",
    "review_requested",
    "review_passed",
    "review_failed",
    "done",
    "failed",
    "stopped",
    "blocked",
    "waiting_input",
    "paused",
    "archived",
    "pr_open",
]

# ---------------------------------------------------------------------------
# Mapping: status -> (recommended, legal_transitions, reason)
#
# recommended: one member of legal[], or None when terminal / waiting
# legal: valid next statuses the owner can trigger from this state
# reason: short human-readable hint shown in the UI
# ---------------------------------------------------------------------------

_MAPPING: dict[str, tuple[Optional[str], list[str], str]] = {
    "todo": (
        "plan_proposed",
        ["plan_proposed"],
        "author a plan handoff before dispatch",
    ),
    "plan_proposed": (
        "plan_approved",
        ["plan_approved", "todo"],
        "review the plan; approve or send back to todo",
    ),
    "plan_approved": (
        "in_progress",
        ["in_progress", "plan_proposed"],
        "dispatch to the agent",
    ),
    "in_progress": (
        None,
        ["report_ready", "pending_user_approval", "stopped", "failed"],
        "agent is working; wait for report_ready or pending_user_approval",
    ),
    "pending_user_approval": (
        "in_progress",
        ["in_progress", "stopped"],
        "answer the agent question then resume",
    ),
    "report_ready": (
        "review_passed",
        ["review_passed", "review_failed", "review_requested"],
        "review diff and handoff, then mark passed or failed",
    ),
    "review_requested": (
        "review_passed",
        ["review_passed", "review_failed"],
        "complete the review",
    ),
    "review_passed": (
        "done",
        ["done", "review_failed"],
        "close the task",
    ),
    "review_failed": (
        "plan_proposed",
        ["plan_proposed", "todo"],
        "revise the plan and re-propose",
    ),
    "done": (
        None,
        [],
        "task is complete",
    ),
    "failed": (
        "plan_proposed",
        ["plan_proposed", "todo", "stopped"],
        "revise the plan and retry, or stop",
    ),
    "stopped": (
        "in_progress",
        ["in_progress", "plan_proposed", "todo"],
        "resume or reopen with a revised plan",
    ),
    "blocked": (
        None,
        ["todo", "plan_proposed"],
        "resolve the blocker first",
    ),
    "waiting_input": (
        None,
        ["in_progress", "pending_user_approval"],
        "waiting for external input",
    ),
    "paused": (
        "in_progress",
        ["in_progress", "stopped"],
        "resume or stop",
    ),
    "archived": (
        None,
        [],
        "task has been archived",
    ),
    "pr_open": (
        "review_passed",
        ["review_passed", "review_failed"],
        "review and merge the open PR",
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class NextAction:
    recommended: Optional[str]
    legal: list[str]
    reason: str

    def as_dict(self) -> dict:
        return {
            "recommended": self.recommended,
            "legal": self.legal,
            "reason": self.reason,
        }


def next_action(status: str) -> NextAction:
    """Return the NextAction for a task in the given status.

    Unknown statuses return an empty legal list with a generic reason so
    consumers degrade gracefully when the state machine evolves.
    """
    entry = _MAPPING.get(status)
    if entry is None:
        return NextAction(recommended=None, legal=[], reason=f"unknown status: {status}")
    recommended, legal, reason = entry
    return NextAction(recommended=recommended, legal=legal, reason=reason)
