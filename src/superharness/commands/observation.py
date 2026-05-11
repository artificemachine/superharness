"""shux observation: lookup observation snapshots by id.

Exposes:
- The pure route helper `route_observation(conn, raw_id)` used by the
  dashboard's `/api/observation/<id>` branch.
- The Click command `cmd_observation_group` registered as `shux observation`,
  with a `show <id>` subcommand for terminal lookup.

The dashboard route and the CLI share the same DAO and the same id parser
so behaviour stays consistent across both surfaces.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import Any, Tuple

import click

from superharness.engine import observations_dao
from superharness.engine.db import get_connection, init_db


def parse_observation_id(raw: str) -> int:
    """Parse a positive integer observation id. Raises ValueError otherwise."""
    if not raw:
        raise ValueError("empty id")
    try:
        n = int(raw)
    except ValueError as exc:
        raise ValueError(f"non-numeric id: {raw!r}") from exc
    if n <= 0:
        raise ValueError(f"id must be positive, got {n}")
    return n


def fetch_observation(conn: sqlite3.Connection, obs_id: int) -> dict[str, Any] | None:
    """DAO read with the route's preferred shape (None for not found)."""
    return observations_dao.get_by_id(conn, obs_id)


def route_observation(
    conn: sqlite3.Connection, raw_id: str
) -> Tuple[dict[str, Any], int]:
    """Pure route handler. Returns (payload, http_status).

    400 on invalid id, 404 on not found, 200 with the row on success.
    """
    try:
        obs_id = parse_observation_id(raw_id)
    except ValueError:
        return ({"error": "invalid id"}, 400)

    row = fetch_observation(conn, obs_id)
    if row is None:
        return ({"error": "not found"}, 404)
    return (row, 200)


@click.group("observation")
def cmd_observation_group() -> None:
    """Inspect observation snapshots stored in this project."""


@cmd_observation_group.command("show")
@click.argument("obs_id")
def cmd_observation_show(obs_id: str) -> None:
    """Print the observation with the given id as JSON.

    Exit codes: 0 found, 1 not found, 2 invalid id.
    """
    project_dir = os.getcwd()
    conn = get_connection(project_dir)
    try:
        init_db(conn, project_dir)
        payload, status = route_observation(conn, obs_id)
    finally:
        conn.close()

    click.echo(json.dumps(payload))
    if status == 200:
        sys.exit(0)
    if status == 404:
        sys.exit(1)
    sys.exit(2)
