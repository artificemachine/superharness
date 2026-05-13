"""DAO for the operator_commands table.

Each row represents one Telegram message processed by the gateway listener.
The idempotency_key (= Telegram message_id stringified) enforces exactly-once
execution even when the Telegram API redelivers updates.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from superharness.engine.state_errors import StateError


@dataclass(frozen=True)
class OperatorCommandRow:
    id: int
    idempotency_key: str
    command: str
    task_id: str | None
    sender_id: str
    status: str
    result: dict[str, Any] | None
    created_at: str
    executed_at: str | None


def insert(
    conn: sqlite3.Connection,
    *,
    idempotency_key: str,
    command: str,
    task_id: str | None,
    sender_id: str,
    now: str,
) -> tuple[OperatorCommandRow, bool]:
    """Insert a new operator command row.

    Returns (row, True) on fresh insert or (existing_row, False) if the
    idempotency_key already exists (duplicate / redelivered message).
    """
    try:
        cursor = conn.execute(
            """
            INSERT INTO operator_commands
                (idempotency_key, command, task_id, sender_id, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            RETURNING id, idempotency_key, command, task_id, sender_id,
                      status, result, created_at, executed_at
            """,
            (idempotency_key, command, task_id, sender_id, now),
        )
        row = cursor.fetchone()
        if not row:
            raise StateError("insert returned no row")
        return _to_row(row), True
    except sqlite3.IntegrityError:
        # UNIQUE constraint on idempotency_key — duplicate message
        existing = get_by_key(conn, idempotency_key)
        if existing is None:
            raise StateError(f"idempotency conflict but row missing: {idempotency_key}")
        return existing, False
    except sqlite3.Error as e:
        raise StateError(f"Failed to insert operator_command: {e}") from e


def get_by_key(
    conn: sqlite3.Connection,
    idempotency_key: str,
) -> OperatorCommandRow | None:
    """Fetch a row by its idempotency_key. Returns None if not found."""
    try:
        cursor = conn.execute(
            """
            SELECT id, idempotency_key, command, task_id, sender_id,
                   status, result, created_at, executed_at
            FROM operator_commands
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        )
        row = cursor.fetchone()
        return _to_row(row) if row else None
    except sqlite3.Error as e:
        raise StateError(f"Failed to fetch operator_command: {e}") from e


def is_duplicate(conn: sqlite3.Connection, idempotency_key: str) -> bool:
    """Return True if this idempotency_key has already been recorded."""
    try:
        cursor = conn.execute(
            "SELECT 1 FROM operator_commands WHERE idempotency_key = ? LIMIT 1",
            (idempotency_key,),
        )
        return cursor.fetchone() is not None
    except sqlite3.Error as e:
        raise StateError(f"Failed to check duplicate: {e}") from e


def update_status(
    conn: sqlite3.Connection,
    row_id: int,
    *,
    status: str,
    result: dict[str, Any] | None = None,
    now: str,
) -> None:
    """Update the status (and optional result) of a processed command."""
    result_json = json.dumps(result) if result is not None else None
    try:
        conn.execute(
            """
            UPDATE operator_commands
            SET status = ?, result = ?, executed_at = ?
            WHERE id = ?
            """,
            (status, result_json, now, row_id),
        )
    except sqlite3.Error as e:
        raise StateError(f"Failed to update operator_command status: {e}") from e


def poll_pending(conn: sqlite3.Connection) -> list[OperatorCommandRow]:
    """Return all rows with status='pending' ordered by id (FIFO).

    Used by the watcher to pick up gateway-issued commands (e.g. Telegram)
    that could not be applied immediately at insert time.
    """
    try:
        cursor = conn.execute(
            """
            SELECT id, idempotency_key, command, task_id, sender_id,
                   status, result, created_at, executed_at
            FROM operator_commands
            WHERE status = 'pending'
            ORDER BY id
            """
        )
        return [_to_row(r) for r in cursor.fetchall()]
    except sqlite3.Error as e:
        raise StateError(f"Failed to poll pending operator_commands: {e}") from e


def _to_row(row: sqlite3.Row) -> OperatorCommandRow:
    result = json.loads(row["result"]) if row["result"] else None
    return OperatorCommandRow(
        id=row["id"],
        idempotency_key=row["idempotency_key"],
        command=row["command"],
        task_id=row["task_id"],
        sender_id=row["sender_id"],
        status=row["status"],
        result=result,
        created_at=row["created_at"],
        executed_at=row["executed_at"],
    )
