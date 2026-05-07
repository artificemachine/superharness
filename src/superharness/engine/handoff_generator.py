"""Handoff generator — creates structured handoff YAML from task state.

Adapted from Pi Mono's structured summary shape:
compact, focused on what was done, what remains, decisions, next steps.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


_NEXT_STEPS_BY_STATUS: dict[str, list[str]] = {
    "todo": ["Create a plan and set status to plan_proposed", "Wait for plan approval"],
    "plan_proposed": ["Wait for operator to approve or reject the plan"],
    "plan_approved": ["Run failing tests (RED)", "Implement to make tests pass (GREEN)", "Submit report handoff"],
    "in_progress": ["Complete implementation", "Run full test suite", "Write report handoff"],
    "waiting_input": ["Provide requested input", "Resume implementation"],
    "report_ready": ["Operator: review report and run shux close <task-id>"],
    "done": ["No further action required"],
    "failed": ["Review failure reason", "Revise plan", "Re-submit as plan_proposed"],
    "blocked": ["Resolve blocker", "Unblock via shux task unblock <task-id>"],
}


def _load_task(project_dir: str, task_id: str) -> dict | None:
    from superharness.engine.state_reader import get_task
    return get_task(project_dir, task_id)


def _tdd_phase(tdd_raw: str | None, status: str) -> str:
    if not tdd_raw:
        return f"Status: {status} (no TDD block defined)"
    try:
        tdd = json.loads(tdd_raw) if isinstance(tdd_raw, str) else tdd_raw
    except (json.JSONDecodeError, TypeError):
        tdd = {}
    if status in ("done", "report_ready"):
        return "GREEN complete — implementation done, tests pass"
    if status == "plan_approved":
        return "RED phase next — write failing tests before implementing"
    if status == "in_progress":
        green = tdd.get("green", "")
        return f"GREEN phase — implementing: {green}" if green else "GREEN phase — implementation in progress"
    return f"Status: {status}"


def _build_compaction(task: dict) -> dict:
    title = str(task.get("title", task.get("id", "unknown")))
    status = str(task.get("status", "todo"))
    criteria = list(task.get("acceptance_criteria") or [])
    context = str(task.get("context") or "")
    out_of_scope = str(task.get("out_of_scope") or "")
    tdd_raw = task.get("tdd")

    goal = f"{title}"
    if criteria:
        goal += f" — done when: {'; '.join(criteria)}"

    constraints: list[str] = []
    if out_of_scope:
        constraints.append(f"Out of scope: {out_of_scope}")
    if context:
        constraints.append(context)
    if not constraints:
        constraints = ["No explicit constraints recorded"]

    progress = _tdd_phase(tdd_raw, status)

    decisions: list[str] = []
    if context:
        decisions.append(context)

    next_steps = _NEXT_STEPS_BY_STATUS.get(status, [f"Advance from status: {status}"])

    return {
        "goal": goal,
        "constraints": constraints,
        "progress": progress,
        "decisions": decisions,
        "next_steps": next_steps,
    }


def generate_handoff(project_dir: str, task_id: str) -> dict:
    """Generate a structured handoff for a task.

    Reads the current contract state and produces a handoff with mandatory
    fields: summary, scope, acceptance, risks, artifacts, compaction.
    """
    task = _load_task(project_dir, task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    status = str(task.get("status", "todo"))
    title = str(task.get("title", task_id))
    criteria = list(task.get("acceptance_criteria") or [])
    context = str(task.get("context", ""))

    status_summary = {
        "todo": "Task not yet started.",
        "in_progress": "Task is actively being worked on.",
        "waiting_input": f"Task paused at {status} — awaiting human input.",
        "report_ready": "Task completed. Ready for review.",
        "done": "Task is complete.",
        "failed": "Task failed.",
        "blocked": "Task is blocked.",
        "archived": "Task has been archived.",
    }

    return {
        "summary": f"{title}: {status_summary.get(status, f'Status: {status}')}",
        "scope": criteria if criteria else [f"Implement {title}"],
        "acceptance": criteria if criteria else ["Task accepted"],
        "risks": ["No risks identified"] if not context else [context],
        "artifacts": [],
        "task": task_id,
        "status": status,
        "generated_at": now,
        "compaction": _build_compaction(task),
    }
