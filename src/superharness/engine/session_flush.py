"""Proactive session flush — save partial work before lifecycle timeout.

Cherry-picked from hermes-agent/gateway/run.py:1033-1069.
"""
import os
from datetime import datetime, timezone

import logging
logger = logging.getLogger(__name__)


def check_expiring(project_dir: str, warning_minutes: int = 15) -> list[str]:
    """Find tasks nearing their lifecycle timeout. Returns list of task IDs."""
    try:
        from superharness.engine import lifecycle_rules
        from superharness.engine.state_reader import get_tasks

        tasks = get_tasks(project_dir)
        rules = lifecycle_rules.LIFECYCLE_RULES
        expiring = []
        now = datetime.now(timezone.utc)

        for task in tasks:
            if not isinstance(task, dict):
                continue
            status = task.get("status", "")
            for rule in rules:
                if rule.source != "contract" or rule.state != status:
                    continue
                ts_str = task.get(rule.timestamp_field, "")
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue
                age_minutes = (now - ts).total_seconds() / 60
                remaining = rule.timeout_minutes - age_minutes
                if 0 < remaining <= warning_minutes:
                    expiring.append(str(task.get("id", "")))
                    break
        return expiring
    except Exception as e:
        logger.warning("session_flush.py unexpected error: %s", e, exc_info=True)
        return []


def flush_task(project_dir: str, task_id: str) -> bool:
    """Write current task context to a handoff file before timeout."""
    try:
        from superharness.engine.state_reader import get_tasks
        tasks = get_tasks(project_dir)
        task = next((t for t in tasks if isinstance(t, dict) and t.get("id") == task_id), None)
        if not task:
            return False

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        handoffs_dir = os.path.join(project_dir, ".superharness", "handoffs")
        os.makedirs(handoffs_dir, exist_ok=True)
        safe_id = task_id.replace("/", "-")
        path = os.path.join(handoffs_dir, f"{safe_id}-auto-flush-{now[:10]}.yaml")

        import yaml
        doc = {
            "task": task_id,
            "phase": "auto-flush",
            "status": task.get("status", "in_progress"),
            "date": now,
            "context": f"[auto-flush] Task nearing lifecycle timeout. "
                       f"Current state: {task.get('status')}. "
                       f"Partial work preserved for next session.",
            "task_snapshot": {
                "status": task.get("status"),
                "acceptance_criteria": task.get("acceptance_criteria", []),
                "context": task.get("context", ""),
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(doc, f, default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        logger.warning("session_flush.py unexpected error: %s", e, exc_info=True)
        return False
