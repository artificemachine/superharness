"""Content-addressed dispatch context — sha256-deduplicated prompt
components recorded per `shux delegate` dispatch.

See docs/PLAN-typed-boundaries-context-hashing.md, Iteration 3. Schema
(migration v39): `context_component`, `dispatch_context`,
`dispatch_context_component` (engine/db.py:_migration_v39).
"""

from __future__ import annotations

import hashlib
import sqlite3

from superharness.engine.state_errors import StateError

COMPONENT_TYPES: frozenset[str] = frozenset(
    {
        "system",
        "task_instructions",
        "discussion_prompt",
        "vault_block",
        "project_rules",
    }
)


def _validate_component_type(component_type: str) -> None:
    if component_type not in COMPONENT_TYPES:
        raise StateError(
            f"Invalid context component type '{component_type}'. "
            f"Valid types: {', '.join(sorted(COMPONENT_TYPES))}"
        )


def record_component(
    conn: sqlite3.Connection,
    *,
    component_type: str,
    content: str,
) -> str:
    """Record a prompt component, deduplicated by sha256 of its content.

    Returns the sha256 hex digest, which is the component's identity —
    identical content recorded twice (even for the same component_type)
    is stored once via INSERT OR IGNORE.
    """
    _validate_component_type(component_type)

    sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO context_component
                (sha256, component_type, content, first_seen)
            VALUES (?, ?, ?, ?)
            """,
            (sha256, component_type, content, _now_utc()),
        )
    except sqlite3.Error as e:
        raise StateError(f"Failed to record context component: {e}") from e

    return sha256


def record_dispatch(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    agent: str,
    components: list[tuple[str, str]],
    now: str,
) -> int:
    """Record one dispatch's ordered list of (component_type, content) pairs.

    Each component is recorded (deduplicated) via record_component, then
    the dispatch's position -> sha256 mapping is stored in
    dispatch_context_component. Returns the new dispatch_context.id.
    """
    # Validate every component type before writing anything, so a bad type at
    # position N cannot leave a dispatch row + N-1 join rows behind in a
    # caller-managed transaction.
    for component_type, _ in components:
        _validate_component_type(component_type)
    try:
        cursor = conn.execute(
            """
            INSERT INTO dispatch_context (task_id, agent, recorded_at)
            VALUES (?, ?, ?)
            """,
            (task_id, agent, now),
        )
        dispatch_id = cursor.lastrowid
        if dispatch_id is None:
            raise StateError("Failed to record dispatch context: no row id returned")

        for position, (component_type, content) in enumerate(components):
            sha256 = record_component(
                conn, component_type=component_type, content=content
            )
            conn.execute(
                """
                INSERT INTO dispatch_context_component
                    (dispatch_id, position, sha256)
                VALUES (?, ?, ?)
                """,
                (dispatch_id, position, sha256),
            )
    except sqlite3.Error as e:
        raise StateError(f"Failed to record dispatch context: {e}") from e

    return dispatch_id


def components_for_dispatch(
    conn: sqlite3.Connection, dispatch_id: int
) -> list[tuple[int, str, str]]:
    """Return (position, component_type, sha256) tuples for a dispatch,
    ordered by position."""
    try:
        rows = conn.execute(
            """
            SELECT dcc.position, cc.component_type, dcc.sha256
            FROM dispatch_context_component dcc
            JOIN context_component cc ON cc.sha256 = dcc.sha256
            WHERE dcc.dispatch_id = ?
            ORDER BY dcc.position ASC
            """,
            (dispatch_id,),
        ).fetchall()
    except sqlite3.Error as e:
        raise StateError(f"Failed to read dispatch context components: {e}") from e

    return [(row[0], row[1], row[2]) for row in rows]


def last_dispatches(
    conn: sqlite3.Connection, *, task_id: str, n: int
) -> list[int]:
    """Return up to n dispatch ids for a task, newest first."""
    try:
        rows = conn.execute(
            """
            SELECT id FROM dispatch_context
            WHERE task_id = ?
            ORDER BY recorded_at DESC, id DESC
            LIMIT ?
            """,
            (task_id, n),
        ).fetchall()
    except sqlite3.Error as e:
        raise StateError(f"Failed to read last dispatches: {e}") from e

    return [row[0] for row in rows]


def _now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
