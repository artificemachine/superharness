"""Subtask lookup and status resolution.

Subtasks are written into `contract.yaml` by the orchestrator (shux delegate
--orchestrate) as planning artifacts. They are not dispatched individually;
the parent task's lifecycle covers them.

This module provides:

- resolve_subtask_status(subtask, parent_status) → str
    Effective status for a subtask: explicit status if set and not the default
    "pending", otherwise inherited from the parent.

- find_task_or_subtask(contract, task_id) → (task_dict, parent_dict | None)
    Locate a task or subtask by id. Subtask ids contain dots (e.g.
    "verify.orchestrator-decompose.1"); the leading segments that match a
    top-level task id identify the parent. Returns (subtask, parent) when
    the id resolves to a subtask, (task, None) for a top-level task, or
    (None, None) if not found.

- iter_all_tasks(contract) → yields dicts
    Walk every top-level task and its subtasks. Each yielded subtask dict
    carries an added "_parent_id" and "_effective_status" key for convenience.
"""
from __future__ import annotations

from typing import Iterator


# Terminal parent statuses that imply subtasks are done by inheritance.
_PARENT_DONE_STATUSES = frozenset({"done", "review_passed"})


def resolve_subtask_status(subtask: dict, parent_status: str | None) -> str:
    """Return the effective status for a subtask.

    Rules:
    - If subtask has an explicit non-default status, use it.
    - If parent is in a terminal-done state, subtask is "done" by inheritance.
    - Otherwise fall back to the subtask's own (possibly "pending") status,
      or "pending" if none set.
    """
    if not isinstance(subtask, dict):
        return "pending"
    explicit = subtask.get("status")
    explicit_s = str(explicit).strip() if explicit is not None else ""
    parent_s = str(parent_status or "").strip()

    # Explicit non-pending status always wins.
    if explicit_s and explicit_s != "pending":
        return explicit_s

    # Parent-done ⇒ inherit done.
    if parent_s in _PARENT_DONE_STATUSES:
        return "done"

    return explicit_s or "pending"


def find_task_or_subtask(
    contract: dict, task_id: str
) -> tuple[dict | None, dict | None]:
    """Locate a task or subtask by id.

    Returns (task_dict, parent_dict | None):
      - (task, None) when task_id matches a top-level task
      - (subtask, parent) when task_id matches a nested subtask
      - (None, None) when not found
    """
    if not isinstance(contract, dict):
        return None, None
    task_id = str(task_id or "")
    tasks = contract.get("tasks") or []
    if not isinstance(tasks, list):
        return None, None

    # First pass: exact top-level match.
    for t in tasks:
        if isinstance(t, dict) and str(t.get("id", "")) == task_id:
            return t, None

    # Second pass: subtask lookup. Match subtask id directly.
    for t in tasks:
        if not isinstance(t, dict):
            continue
        for s in (t.get("subtasks") or []):
            if isinstance(s, dict) and str(s.get("id", "")) == task_id:
                return s, t

    return None, None


def iter_all_tasks(contract: dict) -> Iterator[dict]:
    """Yield every top-level task and every subtask in the contract.

    Subtask dicts are yielded as shallow copies with two extra keys:
    - "_parent_id": id of the owning top-level task
    - "_effective_status": status per resolve_subtask_status
    """
    if not isinstance(contract, dict):
        return
    for t in (contract.get("tasks") or []):
        if not isinstance(t, dict):
            continue
        yield t
        parent_status = str(t.get("status") or "")
        for s in (t.get("subtasks") or []):
            if not isinstance(s, dict):
                continue
            enriched = dict(s)
            enriched["_parent_id"] = str(t.get("id") or "")
            enriched["_effective_status"] = resolve_subtask_status(s, parent_status)
            yield enriched
