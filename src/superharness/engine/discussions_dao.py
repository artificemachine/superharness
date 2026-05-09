from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from superharness.engine.state_errors import StateError


@dataclass(frozen=True)
class DiscussionRow:
    id: str
    task_id: str | None
    topic: str
    owners: list[str]
    status: str
    consensus: str | None
    created_at: str
    closed_at: str | None


@dataclass(frozen=True)
class DiscussionRoundRow:
    id: int
    discussion_id: str
    round_number: int
    agent: str
    content: str | None
    verdict: str | None
    created_at: str


def create(
    conn: sqlite3.Connection,
    *,
    id: str,
    topic: str,
    owners: list[str],
    task_id: str | None = None,
    now: str,
) -> DiscussionRow:
    # If a task_id is provided but the row doesn't exist, treat the FK as
    # SET NULL upfront — tasks() may be created later (or may live only in
    # YAML before migration). The FK is intentionally nullable.
    if task_id:
        exists = conn.execute(
            "SELECT 1 FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not exists:
            task_id = None
    try:
        conn.execute(
            """
            INSERT INTO discussions (id, task_id, topic, owners, status, created_at)
            VALUES (?, ?, ?, ?, 'active', ?)
            """,
            (id, task_id, topic, json.dumps(owners), now),
        )
        row = conn.execute("SELECT * FROM discussions WHERE id = ?", (id,)).fetchone()
        return _row_to_discussion(row)
    except sqlite3.IntegrityError as e:
        raise StateError(f"Discussion '{id}' already exists: {e}") from e
    except sqlite3.Error as e:
        raise StateError(f"Failed to create discussion '{id}': {e}") from e


def get(conn: sqlite3.Connection, id: str) -> DiscussionRow | None:
    row = conn.execute("SELECT * FROM discussions WHERE id = ?", (id,)).fetchone()
    return _row_to_discussion(row) if row else None


def get_all(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    task_id: str | None = None,
) -> list[DiscussionRow]:
    query = "SELECT * FROM discussions WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if task_id:
        query += " AND task_id = ?"
        params.append(task_id)
    query += " ORDER BY created_at DESC"
    return [_row_to_discussion(r) for r in conn.execute(query, params).fetchall()]


def close(
    conn: sqlite3.Connection,
    id: str,
    *,
    consensus: str | None,
    now: str,
) -> bool:
    cursor = conn.execute(
        "UPDATE discussions SET status='closed', consensus=?, closed_at=? WHERE id=? AND status IN ('active', 'consensus')",
        (consensus, now, id),
    )
    return cursor.rowcount > 0


def add_round(
    conn: sqlite3.Connection,
    *,
    discussion_id: str,
    round_number: int,
    agent: str,
    content: str | None = None,
    verdict: str | None = None,
    now: str,
) -> DiscussionRoundRow:
    try:
        cursor = conn.execute(
            """
            INSERT INTO discussion_rounds (discussion_id, round_number, agent, content, verdict, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (discussion_id, round_number, agent, content, verdict, now),
        )
        row = conn.execute(
            "SELECT * FROM discussion_rounds WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return _row_to_round(row)
    except sqlite3.Error as e:
        raise StateError(f"Failed to add round to discussion '{discussion_id}': {e}") from e


def get_rounds(conn: sqlite3.Connection, discussion_id: str) -> list[DiscussionRoundRow]:
    rows = conn.execute(
        "SELECT * FROM discussion_rounds WHERE discussion_id = ? ORDER BY round_number, created_at",
        (discussion_id,),
    ).fetchall()
    return [_row_to_round(r) for r in rows]


def _row_to_discussion(row: sqlite3.Row) -> DiscussionRow:
    return DiscussionRow(
        id=row["id"],
        task_id=row["task_id"],
        topic=row["topic"],
        owners=json.loads(row["owners"]),
        status=row["status"],
        consensus=row["consensus"],
        created_at=row["created_at"],
        closed_at=row["closed_at"],
    )


def _row_to_round(row: sqlite3.Row) -> DiscussionRoundRow:
    return DiscussionRoundRow(
        id=row["id"],
        discussion_id=row["discussion_id"],
        round_number=row["round_number"],
        agent=row["agent"],
        content=row["content"],
        verdict=row["verdict"],
        created_at=row["created_at"],
    )
