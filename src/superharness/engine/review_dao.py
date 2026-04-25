from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from superharness.engine.state_errors import StateError

@dataclass(frozen=True)
class OwnerStats:
    owner: str
    task_count: int
    avg_score: float
    avg_duration_s: float
    fail_rate: float

def record(
    conn: sqlite3.Connection,
    *,
    owner: str,
    task_type: str,
    duration_s: float,
    score: float,
    failed: bool,
    now: str,
) -> None:
    """Record an owner outcome for stats."""
    try:
        conn.execute(
            """
            INSERT INTO review_store (owner, task_type, duration_s, score, failed, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (owner, task_type, duration_s, score, 1 if failed else 0, now)
        )
    except sqlite3.Error as e:
        raise StateError(f"Failed to record review stats for '{owner}': {e}") from e

def stats(conn: sqlite3.Connection, owner: str) -> OwnerStats:
    """Get aggregate stats for an owner."""
    cursor = conn.execute(
        """
        SELECT 
            owner,
            COUNT(*) as task_count,
            AVG(score) as avg_score,
            AVG(duration_s) as avg_duration_s,
            AVG(CAST(failed AS FLOAT)) as fail_rate
        FROM review_store
        WHERE owner = ?
        GROUP BY owner
        """,
        (owner,)
    )
    row = cursor.fetchone()
    if not row:
        return OwnerStats(owner, 0, 0.0, 0.0, 0.0)
    
    return OwnerStats(
        owner=row["owner"],
        task_count=row["task_count"],
        avg_score=row["avg_score"],
        avg_duration_s=row["avg_duration_s"],
        fail_rate=row["fail_rate"]
    )

def rank_owners(
    conn: sqlite3.Connection,
    *,
    task_type: str | None = None,
    min_task_count: int = 3,
) -> list[OwnerStats]:
    """Rank owners by fail_rate ASC, then avg_duration_s ASC."""
    query = """
        SELECT 
            owner,
            COUNT(*) as task_count,
            AVG(score) as avg_score,
            AVG(duration_s) as avg_duration_s,
            AVG(CAST(failed AS FLOAT)) as fail_rate
        FROM review_store
        WHERE 1=1
    """
    params: list[Any] = []
    if task_type:
        query += " AND task_type = ?"
        params.append(task_type)
        
    query += """
        GROUP BY owner
        HAVING task_count >= ?
        ORDER BY fail_rate ASC, avg_duration_s ASC
    """
    params.append(min_task_count)
    
    cursor = conn.execute(query, params)
    return [
        OwnerStats(
            owner=row["owner"],
            task_count=row["task_count"],
            avg_score=row["avg_score"],
            avg_duration_s=row["avg_duration_s"],
            fail_rate=row["fail_rate"]
        )
        for row in cursor.fetchall()
    ]
