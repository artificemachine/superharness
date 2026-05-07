"""MCP ApprovalGate — Iteration 3.

Classifies tool calls by risk level and gates execution.
Low-risk tools auto-approve. Medium/high require explicit operator approval.
Approval state is kept in memory (keyed by approval_id).
"""
from __future__ import annotations

import threading
import uuid
from typing import Literal

RiskLevel = Literal["low", "medium", "high"]

# Tool → risk classification
_RISK_TABLE: dict[str, RiskLevel] = {
    # Read-only → low
    "get_contract":     "low",
    "get_task":         "low",
    "get_ledger":       "low",
    "get_inbox":        "low",
    "get_handoffs":     "low",
    "get_skills":       "low",
    "get_events":       "low",
    "get_contract_summary": "low",
    "run_hygiene":      "low",
    # Write / state-changing → medium
    "create_task":      "medium",
    "update_status":    "medium",
    "enqueue":          "medium",
    "append_ledger":    "medium",
    "append_event":     "medium",
    # Destructive / irreversible → high
    "checkpoint_create": "high",
    "write_handoff":    "high",
    "fire_hook":        "high",
}


def classify_risk(tool: str) -> RiskLevel:
    """Return the risk level for a tool name."""
    return _RISK_TABLE.get(tool, "medium")


class ApprovalPending(Exception):
    """Raised when a tool call requires operator approval."""
    def __init__(self, approval_id: str, tool: str, risk: RiskLevel) -> None:
        super().__init__(f"Approval required for tool '{tool}' (risk={risk}). ID: {approval_id}")
        self.approval_id = approval_id
        self.tool = tool
        self.risk = risk


class ApprovalRejected(Exception):
    """Raised when a previously rejected approval is retried."""


class ApprovalGate:
    """In-memory approval state tracker.

    Approved: auto-approved on next call with same (tool, conn_id).
    Rejected: always raises ApprovalRejected for same (tool, conn_id).
    """

    def __init__(self) -> None:
        # approved_key → True
        self._approved: set[str] = set()
        # approved_key → True (rejected)
        self._rejected: set[str] = set()
        # approval_id → (approved_key, tool)
        self._pending: dict[str, tuple[str, str]] = {}
        self._lock = threading.Lock()

    def _key(self, tool: str, conn_id: str) -> str:
        return f"{conn_id}:{tool}"

    def check(self, tool: str, conn_id: str, project_path: str = "") -> bool:
        """Check if *tool* is allowed for *conn_id*.

        Returns True for auto-approved tools.
        Raises ApprovalPending for medium/high risk tools that haven't been approved.
        Raises ApprovalRejected for previously rejected tools.
        """
        risk = classify_risk(tool)
        key = self._key(tool, conn_id)

        with self._lock:
            if key in self._rejected:
                raise ApprovalRejected(f"Tool '{tool}' was rejected for session '{conn_id}'")
            if key in self._approved:
                return True
            if risk == "low":
                return True

        # Medium/high — require approval
        approval_id = str(uuid.uuid4())
        with self._lock:
            self._pending[approval_id] = (key, tool)
        raise ApprovalPending(approval_id=approval_id, tool=tool, risk=risk)

    def approve(self, approval_id: str) -> None:
        """Mark an approval as granted."""
        with self._lock:
            entry = self._pending.pop(approval_id, None)
            if entry:
                key, _ = entry
                self._approved.add(key)

    def reject(self, approval_id: str) -> None:
        """Mark an approval as rejected."""
        with self._lock:
            entry = self._pending.pop(approval_id, None)
            if entry:
                key, _ = entry
                self._rejected.add(key)
