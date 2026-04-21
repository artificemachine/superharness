"""Subtask resolution gate — evaluate whether a parent task can be marked done.

Design decisions (from plan-subtask-resolution-gate.md):

- Gate is off by default. Opt in per task or per profile.
- Profile wins: profile.require_subtask_resolution=true overrides task-level false.
  Task can tighten (opt in when profile is off), but not loosen.
- Open states that block: pending, in_progress, failed.
- Resolved states that allow close: done, cancelled.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

from superharness.engine.subtask import is_subtask_resolved


@dataclass
class GateResult:
    enabled: bool
    blocking: list[dict]
    source: str  # "profile" | "task" | "none"


def _load_profile(project_dir: str) -> dict:
    path = os.path.join(project_dir, ".superharness", "profile.yaml")
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def evaluate_subtask_gate(task: dict, profile: dict) -> GateResult:
    """Return GateResult for a task given the project profile.

    Profile wins: profile flag overrides task flag.
    Task can opt in even when profile is off.
    """
    profile_flag = bool(profile.get("require_subtask_resolution", False))
    task_flag = bool(task.get("require_subtask_resolution", False))

    enabled = profile_flag or task_flag
    source = "profile" if profile_flag else ("task" if task_flag else "none")

    if not enabled:
        return GateResult(enabled=False, blocking=[], source=source)

    subtasks = task.get("subtasks") or []
    blocking = [
        s for s in subtasks
        if isinstance(s, dict)
        and not is_subtask_resolved(str(s.get("status", "pending")))
    ]

    return GateResult(enabled=True, blocking=blocking, source=source)


def evaluate_subtask_gate_from_disk(task: dict, project_dir: str) -> GateResult:
    """Convenience wrapper that loads the profile from disk."""
    profile = _load_profile(project_dir)
    return evaluate_subtask_gate(task, profile)


def format_gate_error(task_id: str, gate: GateResult) -> str:
    """Return a human-readable error message when the gate blocks a close."""
    sub_ids = ", ".join(str(s.get("id", "?")) for s in gate.blocking)
    source_note = " (enabled by project profile)" if gate.source == "profile" else ""
    lines = [
        f"Cannot close task '{task_id}': {len(gate.blocking)} subtask(s) are still open"
        f"{source_note}: {sub_ids}.",
        "Options:",
        f"  1. Resolve or cancel each subtask, then retry.",
        f"  2. Cancel all remaining open subtasks in one step:",
        f"       shux close --id {task_id} --cancel-remaining --reason \"<why>\"",
        f"  3. Emergency bypass (logs warning in ledger):",
        f"       shux close --id {task_id} --force",
    ]
    return "\n".join(lines)
