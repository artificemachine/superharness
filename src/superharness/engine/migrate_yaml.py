from __future__ import annotations

import os
import sqlite3
import yaml  # type: ignore[import-untyped]
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from superharness.engine.db import transaction, now_iso
from superharness.engine import ledger_dao

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class MigrationReport:
    tasks_imported: int = 0
    inbox_imported: int = 0
    handoffs_imported: int = 0
    failures_imported: int = 0
    decisions_imported: int = 0
    review_imported: int = 0
    errors: list[str] = field(default_factory=list)
    worker_dirs_migrated: list[str] = field(default_factory=list)

def migrate_all_to_sqlite(
    conn: sqlite3.Connection, 
    project_dir: str, 
    workers_root: str | None = None
) -> MigrationReport:
    """Migrate project state from YAML to SQLite."""
    sh_dir = Path(project_dir) / ".superharness"
    report_data: dict[str, Any] = {
        "tasks_imported": 0,
        "inbox_imported": 0,
        "handoffs_imported": 0,
        "failures_imported": 0,
        "decisions_imported": 0,
        "review_imported": 0,
        "errors": [],
        "worker_dirs_migrated": []
    }
    
    now = now_iso()
    
    # 1. Contract (Tasks + Dependencies)
    _migrate_contract(conn, sh_dir, report_data, now)
    
    # 2. Inbox (Main + Workers)
    _migrate_inbox(conn, sh_dir, report_data, now)
    _migrate_worker_inboxes(conn, project_dir, report_data, now, workers_root)
    
    # 3. Handoffs
    _migrate_handoffs(conn, sh_dir, report_data, now)
    
    # 4. Failures
    _migrate_failures(conn, sh_dir, report_data, now)
    
    # 5. Decisions
    _migrate_decisions(conn, sh_dir, report_data, now)
    
    # 6. Review store
    _migrate_review_store(conn, sh_dir, report_data, now)
    
    return MigrationReport(**report_data)

def _safe_load_yaml(path: Path, report_data: dict[str, Any], conn: sqlite3.Connection, now: str) -> Any:
    """Load YAML file with error capturing."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        err_msg = f"Error parsing {path.name}: {e}"
        report_data["errors"].append(err_msg)
        ledger_dao.record(conn, action="migration_error", details={"file": str(path), "error": str(e)}, now=now)
        return None

def _migrate_contract(conn: sqlite3.Connection, sh_dir: Path, report_data: dict[str, Any], now: str) -> None:
    data = _safe_load_yaml(sh_dir / "contract.yaml", report_data, conn, now)
    if not data or not isinstance(data, dict) or "tasks" not in data:
        return
    
    tasks = data["tasks"]
    if not isinstance(tasks, list):
        return
        
    count = 0
    with transaction(conn):
        for t in tasks:
            if not isinstance(t, dict) or "id" not in t:
                continue
            
            # Simple mapping, JSON encode lists/dicts
            ac = json.dumps(t.get("acceptance_criteria", []))
            tt = json.dumps(t.get("test_types", []))
            oos = json.dumps(t.get("out_of_scope", []))
            dod = json.dumps(t.get("definition_of_done", []))
            tdd = json.dumps(t.get("tdd")) if t.get("tdd") else None
            
            # Carry over lifecycle timestamps from YAML so reconcile_lifecycle
            # sees the actual age of the task instead of the migration timestamp.
            updated_at = t.get("updated_at") or now
            in_progress_at = t.get("in_progress_at")
            archived_at = t.get("archived_at")
            created_at = t.get("created_at") or now

            conn.execute("""
                INSERT INTO tasks (
                    id, title, owner, status, effort, project_path,
                    development_method, acceptance_criteria, test_types,
                    out_of_scope, definition_of_done, context, tdd, created_at,
                    updated_at, in_progress_at, archived_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, owner=excluded.owner, status=excluded.status,
                    effort=excluded.effort, project_path=excluded.project_path,
                    development_method=excluded.development_method,
                    acceptance_criteria=excluded.acceptance_criteria,
                    test_types=excluded.test_types, out_of_scope=excluded.out_of_scope,
                    definition_of_done=excluded.definition_of_done,
                    context=excluded.context, tdd=excluded.tdd,
                    updated_at=excluded.updated_at,
                    in_progress_at=excluded.in_progress_at,
                    archived_at=excluded.archived_at
            """, (
                t["id"], t.get("title", "Untitled"), t.get("owner"), t.get("status", "todo"),
                t.get("effort"), t.get("project_path"), t.get("development_method"),
                ac, tt, oos, dod, t.get("context"), tdd, created_at,
                updated_at, in_progress_at, archived_at
            ))

            # Carry over any remaining scalar lifecycle fields whose names
            # match real columns (deadline_minutes, failed_reason, plan_*_at,
            # report_ready_at, review_requested_at, etc.). Skips fields that
            # belong to the structured INSERT above and any unknown keys.
            _scalar_passthrough = {
                "deadline_minutes", "failed_at", "failed_reason",
                "plan_proposed_at", "plan_approved_at", "report_ready_at",
                "review_requested_at", "done_at", "cancelled_at",
                "stopped_at", "pause_reason", "archived_reason",
                "model_tier", "worktree_path", "verified", "verified_at",
                "verified_by", "parent_id", "version",
            }
            for _k in _scalar_passthrough:
                if _k in t and t[_k] is not None:
                    try:
                        conn.execute(
                            f"UPDATE tasks SET {_k} = ? WHERE id = ?",
                            (t[_k], t["id"]),
                        )
                    except sqlite3.OperationalError:
                        pass  # column missing on this schema version
            
            # Dependencies
            blocked_by = t.get("blocked_by", "none")
            if blocked_by and blocked_by != "none":
                deps = [d.strip() for d in str(blocked_by).split(",") if d.strip()]
                conn.execute("DELETE FROM task_dependencies WHERE dependent_task_id = ?", (t["id"],))
                for dep in deps:
                    conn.execute(
                        "INSERT OR IGNORE INTO task_dependencies (dependent_task_id, prerequisite_task_id) VALUES (?, ?)",
                        (t["id"], dep)
                    )
            count += 1
    report_data["tasks_imported"] = count

def _migrate_inbox(conn: sqlite3.Connection, sh_dir: Path, report_data: dict[str, Any], now: str) -> None:
    data = _safe_load_yaml(sh_dir / "inbox.yaml", report_data, conn, now)
    if not data or not isinstance(data, list):
        return
    
    count = 0
    with transaction(conn):
        for item in data:
            if not isinstance(item, dict) or "id" not in item:
                continue
            
            # Check if task exists (FK constraint)
            task_id = item.get("task")
            if not task_id:
                continue
                
            cursor = conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,))
            if not cursor.fetchone():
                report_data["errors"].append(f"Orphaned inbox item {item['id']} references missing task {task_id}")
                continue

            conn.execute("""
                INSERT INTO inbox (
                    id, task_id, target_agent, status, priority, retry_count,
                    max_retries, pid, project_path, plan_only, failed_reason,
                    created_at, launched_at, last_heartbeat, paused_at, failed_at, done_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status, pid=excluded.pid, launched_at=excluded.launched_at
            """, (
                item["id"], task_id, item.get("to", "unknown"), item.get("status", "pending"),
                item.get("priority", 2), item.get("retry_count", 0), item.get("max_retries", 3),
                item.get("pid"), item.get("project"), 1 if item.get("plan_only") else 0,
                item.get("failed_reason"), item.get("created_at", now), item.get("launched_at"),
                item.get("last_heartbeat"), item.get("paused_at"), item.get("failed_at"), item.get("done_at")
            ))
            count += 1
    report_data["inbox_imported"] += count

def _migrate_worker_inboxes(
    conn: sqlite3.Connection, 
    project_dir: str, 
    report_data: dict[str, Any], 
    now: str,
    workers_root: str | None = None
) -> None:
    # Look for workers_root or default to ~/.superharness-workers/
    if workers_root:
        root = Path(workers_root)
    else:
        home = os.environ.get("HOME")
        if not home:
            return
        root = Path(home) / ".superharness-workers"
        
    if not root.exists():
        return
    
    project_abs = os.path.abspath(project_dir)
    sh_path = os.path.join(project_abs, ".superharness")
    
    for worker_dir in root.iterdir():
        if not worker_dir.is_dir():
            continue
        sh_worker = worker_dir / ".superharness"
        if not sh_worker.exists():
            continue
        
        # Check if it's a symlink to this project
        try:
            if sh_worker.is_symlink():
                target = os.path.abspath(os.readlink(sh_worker))
                if target == sh_path or target == project_abs:
                    continue
        except OSError:
            continue
            
        # It's a separate copy, migrate its inbox
        _migrate_inbox(conn, sh_worker, report_data, now)
        report_data["worker_dirs_migrated"].append(str(worker_dir))

def _migrate_handoffs(conn: sqlite3.Connection, sh_dir: Path, report_data: dict[str, Any], now: str) -> None:
    handoffs_dir = sh_dir / "handoffs"
    if not handoffs_dir.exists():
        return
    
    count = 0
    with transaction(conn):
        for h_file in handoffs_dir.glob("*.yaml"):
            try:
                with open(h_file, "r", encoding="utf-8") as f:
                    h = yaml.safe_load(f)
                if not h or not isinstance(h, dict) or "task_id" not in h:
                    continue
                
                # Check task exists
                cursor = conn.execute("SELECT 1 FROM tasks WHERE id = ?", (h["task_id"],))
                if not cursor.fetchone():
                    report_data["errors"].append(f"Orphaned handoff in {h_file.name} references missing task {h['task_id']}")
                    continue
                
                metadata = json.dumps(h.get("metadata", {}))
                
                # We don't have a unique ID in YAML for handoffs, so just insert if not exists
                # Based on task_id + created_at
                created_at = h.get("created_at") or now
                cursor = conn.execute(
                    "SELECT 1 FROM handoffs WHERE task_id = ? AND created_at = ?",
                    (h["task_id"], created_at)
                )
                if cursor.fetchone():
                    continue

                conn.execute("""
                    INSERT INTO handoffs (
                        task_id, phase, status, from_agent, to_agent, content, metadata, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    h["task_id"], h.get("phase", "unknown"), h.get("status", "unknown"),
                    h.get("from_agent"), h.get("to_agent"), h.get("content"),
                    metadata, created_at
                ))
                count += 1
            except Exception as e:
                report_data["errors"].append(f"Error parsing handoff {h_file.name}: {e}")
                
    report_data["handoffs_imported"] = count

def _migrate_failures(conn: sqlite3.Connection, sh_dir: Path, report_data: dict[str, Any], now: str) -> None:
    data = _safe_load_yaml(sh_dir / "failures.yaml", report_data, conn, now)
    if not data or not isinstance(data, dict) or "failures" not in data:
        return
    
    failures = data["failures"]
    if not isinstance(failures, list):
        return
        
    count = 0
    with transaction(conn):
        for f in failures:
            if not isinstance(f, dict):
                continue
            
            # Dedup by task + agent + date
            created_at = f.get("date") or now
            cursor = conn.execute(
                "SELECT 1 FROM failures WHERE task_id = ? AND agent = ? AND created_at = ?",
                (f.get("task"), f.get("agent"), created_at)
            )
            if cursor.fetchone():
                continue

            conn.execute("""
                INSERT INTO failures (task_id, agent, pattern, error_snippet, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                f.get("task"), f.get("agent"), f.get("pattern"),
                f.get("error_snippet"), created_at
            ))
            count += 1
    report_data["failures_imported"] = count

def _migrate_decisions(conn: sqlite3.Connection, sh_dir: Path, report_data: dict[str, Any], now: str) -> None:
    data = _safe_load_yaml(sh_dir / "decisions.yaml", report_data, conn, now)
    if not data or not isinstance(data, dict) or "decisions" not in data:
        return
    
    decisions = data["decisions"]
    if not isinstance(decisions, list):
        return
        
    count = 0
    with transaction(conn):
        for d in decisions:
            if not isinstance(d, dict):
                continue
                
            created_at = d.get("date") or now
            cursor = conn.execute(
                "SELECT 1 FROM decisions WHERE agent = ? AND task_id = ? AND created_at = ?",
                (d.get("agent"), d.get("task"), created_at)
            )
            if cursor.fetchone():
                continue

            alt = json.dumps(d.get("alternatives", []))
            conn.execute("""
                INSERT INTO decisions (agent, task_id, decision, reason, alternatives, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                d.get("agent"), d.get("task"), d.get("decision", "unknown"),
                d.get("reason"), alt, created_at
            ))
            count += 1
    report_data["decisions_imported"] = count

def _migrate_review_store(conn: sqlite3.Connection, sh_dir: Path, report_data: dict[str, Any], now: str) -> None:
    rev_db = sh_dir / "reviews.db"
    if not rev_db.exists():
        return
    
    try:
        src_conn = sqlite3.connect(rev_db)
        src_conn.row_factory = sqlite3.Row
        cursor = src_conn.execute("SELECT * FROM review_store")
        rows = cursor.fetchall()
        
        count = 0
        with transaction(conn):
            for r in rows:
                cols = r.keys()
                task_type = r["task_type"] if "task_type" in cols else ""
                duration_s = r["duration_s"] if "duration_s" in cols else 0.0
                score = r["score"] if "score" in cols else 0.0
                failed = r["failed"] if "failed" in cols else 0
                recorded_at = str(r["recorded_at"]) if "recorded_at" in cols else now
                
                conn.execute("""
                    INSERT INTO review_store (owner, task_type, duration_s, score, failed, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    r["owner"], task_type, duration_s, score, failed, recorded_at
                ))
                count += 1
        src_conn.close()
        report_data["review_imported"] = count
    except Exception as e:
        report_data["errors"].append(f"Error migrating reviews.db: {e}")
