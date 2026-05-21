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

    # Load tasks from state_reader (SQLite)
    try:
        from superharness.engine import state_reader as _sr
        tasks = _sr.get_tasks(str(project_dir))
    except Exception as e:
        logger.warning("auto_schedule.py unexpected error: %s", e, exc_info=True)
        logger.warning("Could not load tasks from state_reader")
        return {"success": False, "error": "Could not load tasks"}

    if not tasks:
        logger.debug("No tasks in contract")
        return {"success": True, "enqueued_tasks": []}

    # Load active inbox items from state_reader (SQLite)
    try:
        inbox = _sr.get_inbox_items(str(project_dir))
    except Exception as e:
        logger.warning("auto_schedule.py unexpected error: %s", e, exc_info=True)
        inbox = []

    # Build set of task IDs already in inbox
    enqueued_task_ids = {str(item.get("task", "")) for item in inbox if isinstance(item, dict) and item.get("task")}

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

    # Write updated inbox via inbox_dao (SQLite)
    if enqueued_tasks:
        try:
            from superharness.engine.db import get_connection, init_db
            from superharness.engine import inbox_dao as _idao
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn = get_connection(str(project_dir))
            try:
                init_db(conn)
                for item in inbox[-len(enqueued_tasks):]:  # only the newly added items
                    _idao.enqueue(conn, id=str(item["id"]), task_id=str(item["task"]),
                                 target_agent=str(item["to"]), priority=int(item.get("priority", 2)),
                                 max_retries=int(item.get("max_retries", 3)),
                                 project_path=str(item.get("project", "")),
                                 plan_only=False, now=now_str, model_override="")
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to enqueue to SQLite: {e}")
        logger.info(f"Enqueued {len(enqueued_tasks)} task(s): {', '.join(enqueued_tasks)}")

    return {
        "success": True,
        "enqueued_tasks": enqueued_tasks,
    }
