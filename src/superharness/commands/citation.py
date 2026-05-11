"""Pure route helpers for citation lookups.

Generalises the iteration-4 observation route to also cover handoff,
decision, and failure rows by integer id. The dashboard wires each
HTTP path to the helper here; the same helper backs CLI lookups when
those are added.

Each kind has a different SQL shape (handoffs has a `metadata` JSON
column, decisions and failures store category/severity/etc), so this
module keeps them explicit rather than building a generic adapter.

Route returns (payload, http_status). 400 on invalid id, 404 on not
found, 200 with the row dict on success.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Tuple

from superharness.commands.observation import parse_observation_id


CITATION_KINDS = {"observation", "handoff", "decision", "failure"}


def _fetch_handoff(conn: sqlite3.Connection, hid: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, task_id, phase, status, from_agent, to_agent, content, metadata, created_at
        FROM handoffs WHERE id = ?
        """,
        (hid,),
    ).fetchone()
    if row is None:
        return None
    out = dict(row)
    try:
        out["metadata"] = json.loads(out["metadata"]) if out["metadata"] else {}
    except (TypeError, ValueError):
        out["metadata"] = {}
    return out


def _fetch_decision(conn: sqlite3.Connection, did: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM decisions WHERE id = ?", (did,)
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def _fetch_failure(conn: sqlite3.Connection, fid: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM failures WHERE id = ?", (fid,)
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def _fetch_observation(conn: sqlite3.Connection, oid: int) -> dict[str, Any] | None:
    from superharness.engine import observations_dao
    return observations_dao.get_by_id(conn, oid)


_FETCHERS = {
    "handoff": _fetch_handoff,
    "decision": _fetch_decision,
    "failure": _fetch_failure,
    "observation": _fetch_observation,
}


def route_citation(
    conn: sqlite3.Connection, kind: str, raw_id: str
) -> Tuple[dict[str, Any], int]:
    """Pure route handler for a citation by kind + id.

    kind must be one of CITATION_KINDS. raw_id is a string from the URL
    path; it must parse as a positive integer.
    """
    if kind not in _FETCHERS:
        return ({"error": "invalid kind"}, 400)
    try:
        cid = parse_observation_id(raw_id)
    except ValueError:
        return ({"error": "invalid id"}, 400)

    row = _FETCHERS[kind](conn, cid)
    if row is None:
        return ({"error": "not found"}, 404)
    return (row, 200)


def route_task_observations(
    conn: sqlite3.Connection, task_id: str
) -> Tuple[dict[str, Any], int]:
    """Return the list of observation snapshots for a task.

    200 with `{task_id, observations}` always (empty list for unknown
    task is normal and not an error: list_for_task returns []). 400 if
    task_id is empty.
    """
    if not task_id:
        return ({"error": "task_id is required"}, 400)
    from superharness.engine import observations_dao
    rows = observations_dao.list_for_task(conn, task_id)
    return ({"task_id": task_id, "observations": rows}, 200)
