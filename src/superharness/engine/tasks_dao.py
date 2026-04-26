from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass, asdict
from typing import Any, cast
from collections import defaultdict

from superharness.engine.state_errors import StateError, ConcurrencyError

@dataclass(frozen=True)
class TaskRow:
    id: str
    title: str
    owner: str | None
    status: str
    effort: str | None
    project_path: str | None
    development_method: str | None
    acceptance_criteria: list[str]
    test_types: list[str]
    out_of_scope: list[str]
    definition_of_done: list[str]
    context: str | None
    tdd: dict[str, Any] | None
    version: int
    created_at: str
    plan_proposed_at: str | None = None
    plan_approved_at: str | None = None
    in_progress_at: str | None = None
    report_ready_at: str | None = None
    done_at: str | None = None
    cancelled_at: str | None = None
    blocked_by: list[str] = None  # type: ignore
    parent_id: str | None = None

def upsert(conn: sqlite3.Connection, task: TaskRow) -> TaskRow:
    """Insert or update a task. Bumps version on update."""
    ac = json.dumps(task.acceptance_criteria)
    tt = json.dumps(task.test_types)
    oos = json.dumps(task.out_of_scope)
    dod = json.dumps(task.definition_of_done)
    tdd = json.dumps(task.tdd) if task.tdd else None
    
    try:
        cursor = conn.execute("""
            INSERT INTO tasks (
                id, title, owner, status, effort, project_path,
                development_method, acceptance_criteria, test_types,
                out_of_scope, definition_of_done, context, tdd, created_at,
                plan_proposed_at, plan_approved_at, in_progress_at,
                report_ready_at, done_at, cancelled_at, version, parent_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title, owner=excluded.owner, status=excluded.status,
                effort=excluded.effort, project_path=excluded.project_path,
                development_method=excluded.development_method,
                acceptance_criteria=excluded.acceptance_criteria,
                test_types=excluded.test_types, out_of_scope=excluded.out_of_scope,
                definition_of_done=excluded.definition_of_done,
                context=excluded.context, tdd=excluded.tdd,
                plan_proposed_at=excluded.plan_proposed_at,
                plan_approved_at=excluded.plan_approved_at,
                in_progress_at=excluded.in_progress_at,
                report_ready_at=excluded.report_ready_at,
                done_at=excluded.done_at,
                cancelled_at=excluded.cancelled_at,
                parent_id=excluded.parent_id,
                version=tasks.version + 1
            RETURNING *
        """, (
            task.id, task.title, task.owner, task.status, task.effort, task.project_path,
            task.development_method, ac, tt, oos, dod, task.context, tdd, task.created_at,
            task.plan_proposed_at, task.plan_approved_at, task.in_progress_at,
            task.report_ready_at, task.done_at, task.cancelled_at, task.version, task.parent_id
        ))
        row = cursor.fetchone()
        if not row:
            raise StateError("Upsert failed: no row returned")
        return _row_to_task(conn, row)
    except sqlite3.Error as e:
        raise StateError(f"Failed to upsert task '{task.id}': {e}") from e

def get(conn: sqlite3.Connection, id: str) -> TaskRow | None:
    """Get a task by ID, including its dependencies."""
    cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (id,))
    row = cursor.fetchone()
    if not row:
        return None
    return _row_to_task(conn, row)

def get_all(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    owner: str | None = None,
    top_level_only: bool = False,
) -> list[TaskRow]:
    """Get all tasks, optionally filtered by status, owner, or top-level only (parent_id IS NULL)."""
    query = "SELECT * FROM tasks WHERE 1=1"
    params: list[Any] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if owner:
        query += " AND owner = ?"
        params.append(owner)
    if top_level_only:
        query += " AND parent_id IS NULL"
    
    query += " ORDER BY created_at ASC"
    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    
    # Optimized: Fetch all dependencies for these tasks in one query
    if not rows:
        return []
        
    task_ids = [r["id"] for r in rows]
    placeholders = ",".join(["?" for _ in task_ids])
    dep_cursor = conn.execute(
        f"SELECT dependent_task_id, prerequisite_task_id FROM task_dependencies WHERE dependent_task_id IN ({placeholders})",
        task_ids
    )
    deps_map = defaultdict(list)
    for dep_row in dep_cursor.fetchall():
        deps_map[dep_row[0]].append(dep_row[1])
        
    return [_row_to_task(conn, row, deps_map[row["id"]]) for row in rows]

def update(
    conn: sqlite3.Connection,
    id: str,
    version: int,
    changes: dict[str, Any],
) -> TaskRow:
    """Update specific fields of a task with optimistic concurrency check."""
    if not changes:
        task = get(conn, id)
        if not task: raise StateError(f"Task {id} not found")
        return task

    set_clauses = []
    params: list[Any] = []
    for key, value in changes.items():
        if key in ("acceptance_criteria", "test_types", "out_of_scope", "definition_of_done"):
            set_clauses.append(f"{key} = ?")
            params.append(json.dumps(value))
        elif key == "tdd":
            set_clauses.append(f"{key} = ?")
            params.append(json.dumps(value) if value else None)
        else:
            set_clauses.append(f"{key} = ?")
            params.append(value)
            
    set_clauses.append("version = version + 1")
    sql = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ? AND version = ? RETURNING *"
    params.extend([id, version])
    
    try:
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        if not row:
            # Check if it was a version mismatch or missing ID
            cursor = conn.execute("SELECT version FROM tasks WHERE id = ?", (id,))
            existing = cursor.fetchone()
            if existing:
                raise ConcurrencyError(f"Task '{id}' version mismatch: expected {version}, got {existing['version']}")
            else:
                raise StateError(f"Task '{id}' not found")
        return _row_to_task(conn, row)
    except sqlite3.Error as e:
        raise StateError(f"Failed to update task '{id}': {e}") from e

def set_dependencies(
    conn: sqlite3.Connection,
    task_id: str,
    prerequisites: list[str],
) -> None:
    """Replace dependencies for a task."""
    try:
        conn.execute("DELETE FROM task_dependencies WHERE dependent_task_id = ?", (task_id,))
        for prereq in prerequisites:
            conn.execute(
                "INSERT INTO task_dependencies (dependent_task_id, prerequisite_task_id) VALUES (?, ?)",
                (task_id, prereq)
            )
    except sqlite3.Error as e:
        raise StateError(f"Failed to set dependencies for task '{task_id}': {e}") from e

def get_unblocked(
    conn: sqlite3.Connection,
    *,
    status_filter: list[str] | None = None,
) -> list[TaskRow]:
    """Get tasks whose prerequisites are all 'done'."""
    query = """
        SELECT * FROM tasks t
        WHERE NOT EXISTS (
            SELECT 1 FROM task_dependencies d
            JOIN tasks p ON d.prerequisite_task_id = p.id
            WHERE d.dependent_task_id = t.id AND p.status != 'done'
        )
    """
    params: list[Any] = []
    if status_filter:
        query += f" AND t.status IN ({','.join(['?' for _ in status_filter])})"
        params.extend(status_filter)
        
    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    if not rows:
        return []
        
    task_ids = [r["id"] for r in rows]
    placeholders = ",".join(["?" for _ in task_ids])
    dep_cursor = conn.execute(
        f"SELECT dependent_task_id, prerequisite_task_id FROM task_dependencies WHERE dependent_task_id IN ({placeholders})",
        task_ids
    )
    deps_map = defaultdict(list)
    for dep_row in dep_cursor.fetchall():
        deps_map[dep_row[0]].append(dep_row[1])

    return [_row_to_task(conn, row, deps_map[row["id"]]) for row in rows]

def _row_to_task(conn: sqlite3.Connection, row: sqlite3.Row, blocked_by: list[str] | None = None) -> TaskRow:
    if blocked_by is None:
        task_id = row["id"]
        cursor = conn.execute(
            "SELECT prerequisite_task_id FROM task_dependencies WHERE dependent_task_id = ?",
            (task_id,)
        )
        blocked_by = [r[0] for r in cursor.fetchall()]
    
    keys = row.keys() if hasattr(row, "keys") else []
    return TaskRow(
        id=row["id"],
        title=row["title"],
        owner=row["owner"],
        status=row["status"],
        effort=row["effort"],
        project_path=row["project_path"],
        development_method=row["development_method"],
        acceptance_criteria=json.loads(row["acceptance_criteria"]),
        test_types=json.loads(row["test_types"]),
        out_of_scope=json.loads(row["out_of_scope"]),
        definition_of_done=json.loads(row["definition_of_done"]),
        context=row["context"],
        tdd=json.loads(row["tdd"]) if row["tdd"] else None,
        version=row["version"],
        created_at=row["created_at"],
        plan_proposed_at=row["plan_proposed_at"],
        plan_approved_at=row["plan_approved_at"],
        in_progress_at=row["in_progress_at"],
        report_ready_at=row["report_ready_at"],
        done_at=row["done_at"],
        cancelled_at=row["cancelled_at"],
        blocked_by=blocked_by,
        parent_id=row["parent_id"] if "parent_id" in keys else None,
    )
