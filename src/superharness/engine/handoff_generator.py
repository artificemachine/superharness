"""Handoff generator — creates structured handoff YAML from task state.

Adapted from Pi Mono's structured summary shape:
compact, focused on what was done, what remains, decisions, next steps.
"""
from __future__ import annotations

from datetime import datetime, timezone


def generate_handoff(project_dir: str, task_id: str) -> dict:
    """Generate a structured handoff for a task.

    Reads the current contract state and produces a handoff with mandatory
    fields: summary, scope, acceptance, risks, artifacts.
    """
    from superharness.engine.state_reader import get_task

    task = get_task(project_dir, task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    status = str(task.get("status", "todo"))
    title = str(task.get("title", task_id))
    criteria = list(task.get("acceptance_criteria") or [])
    context = str(task.get("context", ""))

    # Map status to summary language
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
    }
