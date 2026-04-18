"""Shared task lifecycle helpers.

Centralizes workflow inference and per-workflow allowed-status sets so that
the enqueue gate (`inbox_enqueue`) and dispatch gate (`delegate`) stay in
lockstep. When they drift (e.g. enqueue accepts what dispatch rejects), the
launcher wastes retry cycles on permanently-blocked work — see the synod
2026-04-15 regression for the motivating incident.
"""
from __future__ import annotations

import re

_DISC_ROUND_RE = re.compile(r"^(discuss-[^/]+)/round-(\d+)$")

TERMINAL_STATUSES = frozenset({"done", "failed", "stopped"})


def infer_workflow(task_id: str, task_obj: dict | None) -> str:
    """Return the workflow name for a task.

    Priority: explicit `workflow` field on the task → discussion-round pattern
    → default `implementation`.
    """
    workflow = ""
    if isinstance(task_obj, dict):
        workflow = str(task_obj.get("workflow", "") or "").strip().lower()
    if workflow:
        return workflow
    if _DISC_ROUND_RE.match(task_id):
        return "discussion"
    return "implementation"


def allowed_statuses_for_workflow(workflow: str, *, for_review: bool = False) -> set[str]:
    """Return the set of statuses at which a task is dispatchable.

    Terminal statuses (done/failed/stopped) are not included here — callers
    must handle them separately because reconcile logic differs (failed and
    stopped are re-dispatchable; done is not).
    """
    if workflow == "implementation":
        allowed = {
            "plan_approved",
            "in_progress",
            "report_ready",
            "review_passed",
            "pr_open",
            "review_failed",
            "pending_user_approval",
        }
        if for_review:
            allowed.add("review_requested")
        return allowed
    if workflow == "quick":
        return {"todo", "in_progress", "report_ready", "failed", "stopped"}
    if workflow == "note":
        return {"todo", "in_progress", "failed", "stopped"}
    if workflow == "discussion":
        return {"todo", "in_progress"}
    if workflow == "review":
        allowed = {"todo", "in_progress", "review_requested", "review_failed"}
        if for_review:
            allowed.add("review_passed")
        return allowed
    if workflow == "approval":
        return {"pending_user_approval"}
    return {"plan_approved", "in_progress"}


def plan_only_allowed_statuses(workflow: str) -> set[str]:
    """Statuses at which a `--plan-only` dispatch is acceptable.

    For the implementation workflow, this additionally allows `todo` and
    `plan_proposed` — the agent is expected to write (or revise) a plan and
    stop before touching any implementation code. Non-implementation
    workflows inherit their normal allowed set (plan-only is a no-op there).
    """
    if workflow == "implementation":
        return {"todo", "plan_proposed", "plan_approved", "review_failed"}
    return allowed_statuses_for_workflow(workflow)
