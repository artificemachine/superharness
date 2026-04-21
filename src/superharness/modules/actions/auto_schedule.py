"""Auto-schedule module actions — enqueue tasks when scheduled_after arrives."""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _generate_inbox_id(task_id: str) -> str:
    """Generate a unique inbox item ID.

    Format: YYYYMMDDTHHMMSSz-{task_id}-{pid}-{random}
    """
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    pid = os.getpid()
    random_suffix = secrets.token_hex(3)
    return f"{timestamp}-{task_id}-{pid}-{random_suffix}"


def check_scheduled_tasks(context: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Scan contract for tasks ready to delegate. Returns list of enqueued task IDs.

    Args:
        context: Context dict with project_dir
        settings: Module settings with auto_target, check_depends_on

    Returns:
        Result dict with success status and enqueued_tasks list
    """
    project_dir = Path(context.get("project_dir", "."))
    harness_dir = project_dir / ".superharness"

    contract_file = harness_dir / "contract.yaml"
    inbox_file = harness_dir / "inbox.yaml"

    if not contract_file.exists():
        logger.warning(f"No contract found at {contract_file}")
        return {"success": False, "error": "No contract found"}

    # Load contract
    from superharness.engine.yaml_helpers import safe_load
    contract = safe_load(str(contract_file), dict)

    tasks = contract.get("tasks", [])
    if not tasks:
        logger.debug("No tasks in contract")
        return {"success": True, "enqueued_tasks": []}

    # Load inbox
    if inbox_file.exists():
        inbox = safe_load(str(inbox_file), list)
    else:
        inbox = []

    # Build set of task IDs already in inbox
    enqueued_task_ids = {item["task"] for item in inbox if isinstance(item, dict) and "task" in item}

    # Build map of task statuses for dependency checking
    task_status_map = {}
    for task in tasks:
        if isinstance(task, dict) and "id" in task:
            task_status_map[task["id"]] = task.get("status", "todo")

    # Scan for tasks ready to delegate
    auto_target = settings.get("auto_target", "claude-code")
    check_depends_on = settings.get("check_depends_on", True)
    today = datetime.now().date()

    enqueued_tasks = []

    for task in tasks:
        if not isinstance(task, dict):
            continue

        task_id = task.get("id")
        if not task_id:
            continue

        # Skip if not status=todo
        status = task.get("status", "todo")
        if status != "todo":
            continue

        # Skip if already in inbox
        if task_id in enqueued_task_ids:
            logger.debug(f"Task {task_id} already in inbox, skipping")
            continue

        # Only process tasks with scheduled_after field
        scheduled_after_str = task.get("scheduled_after")
        if not scheduled_after_str:
            # Skip tasks without scheduled_after (not auto-scheduled)
            continue

        # Parse and check scheduled_after date
        try:
            scheduled_date = datetime.strptime(str(scheduled_after_str), "%Y-%m-%d").date()
            if scheduled_date > today:
                logger.debug(f"Task {task_id} scheduled for {scheduled_date}, not ready yet")
                continue
        except ValueError:
            logger.warning(f"Invalid scheduled_after format for task {task_id}: {scheduled_after_str}")
            continue

        # Check dependencies
        if check_depends_on:
            depends_on = task.get("depends_on")
            if depends_on:
                dep_status = task_status_map.get(depends_on, "todo")
                if dep_status not in ("done", "archived"):
                    logger.debug(f"Task {task_id} blocked by dependency {depends_on} (status={dep_status})")
                    continue

        # Task is ready to enqueue
        logger.info(f"Auto-enqueuing task {task_id} → {auto_target}")

        inbox_item = {
            "id": _generate_inbox_id(task_id),
            "task": task_id,
            "to": auto_target,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "project": str(project_dir),
            "priority": 2,
            "max_retries": 3,
            "retry_count": 0,
        }

        inbox.append(inbox_item)
        enqueued_tasks.append(task_id)

    # Write updated inbox
    if enqueued_tasks:
        import yaml
        with open(inbox_file, "w") as f:
            f.write("# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n")
            yaml.dump(inbox, f, default_flow_style=False, allow_unicode=True)
        logger.info(f"Enqueued {len(enqueued_tasks)} task(s): {', '.join(enqueued_tasks)}")

    return {
        "success": True,
        "enqueued_tasks": enqueued_tasks,
    }
