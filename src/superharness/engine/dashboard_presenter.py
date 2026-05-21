from __future__ import annotations

import sqlite3
import json
from dataclasses import asdict
from typing import Any
from collections import defaultdict
from pathlib import Path

from superharness.engine import tasks_dao, inbox_dao, failures_dao, decisions_dao, ledger_dao, state_reader

import logging
logger = logging.getLogger(__name__)

def get_dashboard_status_snapshot(conn: sqlite3.Connection, project_dir: str) -> dict[str, Any]:
    """Return a comprehensive snapshot of the project state for the dashboard.
    
    Uses state_reader to merge YAML definitions with SQLite runtime state.
    """
    # 1. Tasks & Contract ID
    tasks_as_dict = state_reader.get_tasks(project_dir)
    
    contract_id = "unknown"
    try:
        doc = state_reader.get_contract_doc(project_dir)
        contract_id = str(doc.get("id", "initial-setup"))
    except Exception as e:
        logger.warning("dashboard_presenter.py unexpected error: %s", e, exc_info=True)
        pass
    # 2. Inbox
    inbox_as_dict = state_reader.get_inbox_items(project_dir)
    
    # 3. Active discussions — read from SQLite (canonical source)
    active_discussions = []
    try:
        from superharness.engine import discussions_dao
        for row in discussions_dao.get_all(conn):
            if row.status in ("active", "consensus"):
                rounds = discussions_dao.get_rounds(conn, row.id)
                submitted = len(rounds)
                participants = row.owners or []
                total = len(participants)
                verdicts = [r.verdict for r in rounds]
                active_discussions.append({
                    "id": row.id,
                    "topic": row.topic or "",
                    "status": row.status,
                    "current_round": submitted + 1,
                    "max_rounds": 3,
                    "participants": participants,
                    "created_at": row.created_at or "",
                    "task_id": row.task_id,
                    "verdicts": {r.agent: r.verdict for r in rounds},
                    "submitted_count": submitted,
                    "all_submitted": total > 0 and submitted >= total,
                    "all_consensus": total > 0 and submitted >= total and all(v == "consensus" for v in verdicts),
                    "closed_at": row.closed_at or "",
                })
    except Exception as e:
        logger.warning("dashboard_presenter.py unexpected error: %s", e, exc_info=True)
        pass
    # 4. Failures & Decisions
    failures = [asdict(f) for f in failures_dao.get_recent(conn, limit=50)]
    decisions = [asdict(d) for d in decisions_dao.get_recent(conn, limit=50)]
    
    # 4. Activity Feed (Unified ledger)
    ledger = state_reader.get_ledger_entries(project_dir, limit=100)
    activity: list[dict[str, Any]] = []
    for l in ledger:
        action = str(l.get("action", ""))
        action_lower = action.lower()
        if "gc" in action_lower:
            etype = "gc"
        elif "dispatch" in action_lower or "claim" in action_lower:
            etype = "dispatch"
        elif "review" in action_lower:
            etype = "review"
        else:
            etype = "ledger"
            
        details_str = ""
        details = l.get("details")
        if isinstance(details, dict):
            if "error" in details:
                details_str = f" — Error: {details['error']}"
            elif "task" in details:
                details_str = f" — {details['task']}"
                
        activity.append({
            "time": str(l.get("created_at", "")),
            "type": etype,
            "message": f"{action}{details_str}"
        })
    
    # Derived stats
    inbox_counts: dict[str, int] = defaultdict(int)
    inbox_owners: dict[str, int] = defaultdict(int)
    for i in inbox_as_dict:
        inbox_counts[str(i.get("status", ""))] += 1
        inbox_owners[str(i.get("to", ""))] += 1
        
    active_inbox_tasks = [str(i.get("task", "")) for i in inbox_as_dict if i.get("status") in ("pending", "launched", "running")]
    paused_inbox_tasks = [str(i.get("task", "")) for i in inbox_as_dict if i.get("status") == "paused"]
    failed_inbox_tasks = [str(i.get("task", "")) for i in inbox_as_dict if i.get("status") in ("failed", "stale")]
    done_inbox_tasks = [str(i.get("task", "")) for i in inbox_as_dict if i.get("status") == "done"]
    
    # Board columns — map raw statuses to the 6 display columns
    _STATUS_TO_COL = {
        "todo": "todo",
        "plan_proposed": "plan", "plan_approved": "plan",
        "in_progress": "active", "launched": "active", "running": "active",
        "report_ready": "review", "review_requested": "review",
        "review_passed": "review", "review_failed": "review",
        "done": "done", "failed": "done", "archived": "done",
        "stopped": "stopped",
    }
    board_columns: dict[str, list[dict[str, Any]]] = {
        "todo": [], "plan": [], "active": [], "review": [], "done": [], "stopped": []
    }
    for t in tasks_as_dict:
        st = str(t.get("status", "todo"))
        col = _STATUS_TO_COL.get(st, "todo")
        board_columns[col].append(t)
        
    # Review queue
    review_queue = [t for t in tasks_as_dict if str(t.get("status", "")) in {"report_ready", "review_requested", "review_passed", "review_failed"}]
    
    # All task owners
    KNOWN_AGENTS = ["claude-code", "codex-cli", "gemini-cli", "opencode"]
    all_task_owners = list(set(KNOWN_AGENTS) | set(str(t.get("owner", "")) for t in tasks_as_dict if t.get("owner")) | set(str(i.get("to", "")) for i in inbox_as_dict if i.get("to")))

    # Active dispatch worktrees — tasks with a worktree_path where the directory
    # still exists on disk.  worktree_path is never cleared on cleanup, so the
    # directory existence check is the authoritative signal.
    # Empty list means the section is omitted on the consumer side.
    import os as _os
    worktrees = [
        {
            "path": str(t.get("worktree_path", "")),
            "task_id": str(t.get("id", "")),
            "created_at": str(t.get("created_at", "")),
        }
        for t in tasks_as_dict
        if t.get("worktree_path") and _os.path.isdir(str(t.get("worktree_path", "")))
    ]

    snapshot = {
        "contract_id": contract_id,
        "contract_tasks": tasks_as_dict,
        "contract_owners": list(set(str(t.get("owner", "")) for t in tasks_as_dict if t.get("owner"))),
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
        "worktrees": worktrees,
        "ledger_tail": [f"- {l.get('created_at', '')} — {l.get('action', '')} ({l.get('agent', 'system')})"
                        for l in ledger[:50]
                        if l.get('action', '') != 'tick'][:18],
    }

    # Attach log tails from watcher/daemon output files
    _attach_log_tails(snapshot, project_dir)

    return snapshot


def _attach_log_tails(snapshot: dict, project_dir: str) -> None:
    """Attach daemon out/err log tails to the snapshot."""
    import os
    log_dir = os.path.join(project_dir, ".superharness", "launcher-logs")
    for key, filename in [("out_tail", "daemon.out.log"), ("err_tail", "daemon.err.log")]:
        path = os.path.join(log_dir, filename)
        if os.path.isfile(path):
            try:
                with open(path, "r", errors="replace") as f:
                    lines = f.readlines()[-50:]  # last 50 lines
                snapshot[key] = [l.rstrip("\n") for l in lines]
            except Exception as e:
                logger.warning("dashboard_presenter.py unexpected error: %s", e, exc_info=True)
                snapshot[key] = []
        else:
            snapshot[key] = []

def get_task_report_data(conn: sqlite3.Connection, task_id: str, project_dir: str) -> dict[str, Any] | None:
    """Return task data structured for the task report UI."""
    task = state_reader.get_task(project_dir, task_id)
    if not task:
        return None
        
    result = {
        "contract_status":   task.get("status", "todo"),
        "contract_title":    task.get("title", ""),
        "contract_owner":    task.get("owner", ""),
        "contract_summary":  task.get("summary", ""),
        "blocked_by":        task.get("blocked_by", []),
        "acceptance_criteria": task.get("acceptance_criteria", []),
        "test_types":        task.get("test_types", []),
        "tdd":               task.get("tdd", {}),
        "plan_proposed_at":  task.get("plan_proposed_at"),
        "plan_approved_at":  task.get("plan_approved_at"),
        "in_progress_at":    task.get("in_progress_at"),
        "report_ready_at":   task.get("report_ready_at"),
        "done_at":           task.get("done_at"),
    }
    return result

def get_task_instructions_data(conn: sqlite3.Connection, task_id: str, project_dir: str) -> dict[str, Any] | None:
    """Get metadata for task instructions from state_reader."""
    task = state_reader.get_task(project_dir, task_id)
    if not task:
        return None
    return {
        "title": task.get("title", ""),
        "acceptance_criteria": task.get("acceptance_criteria", []),
        "owner": task.get("owner", "claude-code"),
        "status": task.get("status", "todo"),
        "workflow": task.get("workflow", "implementation"),
    }
