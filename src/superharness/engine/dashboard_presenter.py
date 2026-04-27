from __future__ import annotations

import sqlite3
import json
from dataclasses import asdict
from typing import Any
from collections import defaultdict
from pathlib import Path

from superharness.engine import tasks_dao, inbox_dao, handoffs_dao, failures_dao, decisions_dao, ledger_dao, discussions_dao

def get_dashboard_status_snapshot(conn: sqlite3.Connection, project_dir: str) -> dict[str, Any]:
    """Return a comprehensive snapshot of the project state for the dashboard.
    
    This replaces multiple YAML reads with a single set of SQLite queries.
    """
    # 1. Tasks
    all_tasks = tasks_dao.get_all(conn)
    tasks_as_dict = [asdict(t) for t in all_tasks]
    
    # 2. Inbox
    all_inbox = inbox_dao.get_all(conn)
    inbox_as_dict = [asdict(i) for i in all_inbox]
    
    # 3. Active discussions — read from YAML state files (discussions not yet in SQLite)
    active_discussions = []
    try:
        import yaml as _yaml
        disc_root = Path(project_dir) / ".superharness" / "discussions"
        if disc_root.exists():
            for state_file in disc_root.glob("*/state.yaml"):
                try:
                    st = _yaml.safe_load(state_file.read_text(encoding="utf-8", errors="replace")) or {}
                    if st.get("status") == "active":
                        active_discussions.append({
                            "id": st.get("id", state_file.parent.name),
                            "topic": st.get("topic", ""),
                            "status": st.get("status", ""),
                            "current_round": st.get("current_round", "?"),
                            "max_rounds": st.get("max_rounds", "?"),
                            "participants": st.get("participants") or [],
                            "created_at": st.get("created_at", ""),
                            "task_id": st.get("task_id"),
                        })
                except Exception:
                    pass
    except Exception:
        pass

    # 4. Failures & Decisions
    failures = [asdict(f) for f in failures_dao.get_recent(conn, limit=50)]
    decisions = [asdict(d) for d in decisions_dao.get_recent(conn, limit=50)]
    
    # 4. Activity Feed (Unified ledger)
    ledger = ledger_dao.get_recent(conn, limit=100)
    activity: list[dict[str, Any]] = []
    for l in ledger:
        # Determine type from action
        action_lower = l.action.lower()
        if "gc" in action_lower:
            etype = "gc"
        elif "dispatch" in action_lower or "claim" in action_lower:
            etype = "dispatch"
        elif "review" in action_lower:
            etype = "review"
        else:
            etype = "ledger"
            
        details_str = ""
        if l.details:
            if "error" in l.details:
                details_str = f" — Error: {l.details['error']}"
            elif "task" in l.details:
                details_str = f" — {l.details['task']}"
                
        activity.append({
            "time": l.created_at,
            "type": etype,
            "message": f"{l.action}{details_str}"
        })
    
    # Derived stats
    inbox_counts: dict[str, int] = defaultdict(int)
    inbox_owners: dict[str, int] = defaultdict(int)
    for i in all_inbox:
        inbox_counts[i.status] += 1
        inbox_owners[i.target_agent] += 1
        
    active_inbox_tasks = [i.task_id for i in all_inbox if i.status in ("pending", "launched", "running")]
    paused_inbox_tasks = [i.task_id for i in all_inbox if i.status == "paused"]
    failed_inbox_tasks = [i.task_id for i in all_inbox if i.status in ("failed", "stale")]
    done_inbox_tasks = [i.task_id for i in all_inbox if i.status == "done"]
    
    # Board columns
    board_columns: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in tasks_as_dict:
        board_columns[t["status"]].append(t)
        
    # Review queue
    review_queue = [t for t in tasks_as_dict if t["status"] in {"review_requested", "review_passed", "review_failed"}]
    
    # All task owners
    KNOWN_AGENTS = ["claude-code", "codex-cli", "gemini-cli"]
    all_task_owners = list(set(KNOWN_AGENTS) | set(t["owner"] for t in tasks_as_dict if t["owner"]) | set(i.target_agent for i in all_inbox))

    return {
        "contract_id": "initial-setup", # Hardcoded until contract table has metadata
        "contract_tasks": tasks_as_dict,
        "contract_owners": list(set(t["owner"] for t in tasks_as_dict if t["owner"])),
        "all_task_owners": all_task_owners,
        "active_inbox_tasks": active_inbox_tasks,
        "paused_inbox_tasks": paused_inbox_tasks,
        "failed_inbox_tasks": failed_inbox_tasks,
        "done_inbox_tasks": done_inbox_tasks,
        "inbox_counts": dict(inbox_counts),
        "inbox_owners": dict(inbox_owners),
        "review_queue_count": len(review_queue),
        "review_queue": review_queue,
        "board_columns": dict(board_columns),
        "activity_feed": activity,
        "inbox_items": inbox_as_dict,
        "active_discussions": active_discussions,
        "failures": failures,
        "decisions": decisions,
        "ledger_tail": [f"- {l.created_at} — {l.action} ({l.agent or 'system'})" for l in ledger[:18]]
    }

def get_task_report_data(conn: sqlite3.Connection, task_id: str) -> dict[str, Any] | None:
    """Return task data structured for the task report UI."""
    task = tasks_dao.get(conn, task_id)
    if not task:
        return None
        
    result = {
        "contract_status":   task.status,
        "contract_title":    task.title,
        "contract_owner":    task.owner or "",
        "blocked_by":        task.blocked_by,
        "acceptance_criteria": task.acceptance_criteria,
        "test_types":        task.test_types,
        "tdd":               task.tdd or {},
        "plan_proposed_at":  task.plan_proposed_at,
        "plan_approved_at":  task.plan_approved_at,
        "in_progress_at":    task.in_progress_at,
        "report_ready_at":   task.report_ready_at,
        "done_at":           task.done_at,
    }
    return result

def get_task_instructions_data(conn: sqlite3.Connection, task_id: str) -> dict[str, Any] | None:
    """Get metadata for task instructions from SQLite."""
    task = tasks_dao.get(conn, task_id)
    if not task:
        return None
    return {
        "title": task.title,
        "acceptance_criteria": task.acceptance_criteria,
        "owner": task.owner or "claude-code",
        "status": task.status,
        "workflow": "implementation", # default
    }
