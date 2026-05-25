"""Agent status contract v1 — runtime-agnostic file-based heartbeat.

Each agent runtime writes a status file to:
  .superharness/agents/<runtime>.status.yaml

The schema is identical regardless of whether the runtime is a native agent
(claude-code, codex-cli) or an external runtime.  Readers never hardcode
runtime names — they discover files by scanning the agents/ directory.

Schema (schema_version 1):
  schema_version: "1"
  runtime:        str       # e.g. "claude-code", "my-custom-bot"
  updated_at:     str       # ISO-8601 UTC timestamp
  liveness:       str       # active | idle | stopping | dead
  active_task:    str|null  # current contract task ID
  next_wake_at:   str|null  # ISO-8601 UTC of next scheduled wake, or null
  budget:         dict|null # model, input_tokens, output_tokens, cost_usd, max_budget_usd
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

import logging
logger = logging.getLogger(__name__)


SCHEMA_VERSION = "1"
VALID_LIVENESS = frozenset({"active", "idle", "stopping", "dead"})


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class AgentStatusRecord:
    """Runtime-agnostic agent status record (heartbeat contract v1)."""

    runtime: str
    updated_at: str
    schema_version: str = SCHEMA_VERSION
    liveness: str = "active"
    active_task: str | None = None
    next_wake_at: str | None = None
    budget: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _agents_dir(project_dir: Path) -> Path:
    return Path(project_dir) / ".superharness" / "agents"


def _status_path(project_dir: Path, runtime: str) -> Path:
    return _agents_dir(project_dir) / f"{runtime}.status.yaml"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_agent_status(
    project_dir: Path | str,
    *,
    runtime: str,
    liveness: str = "active",
    active_task: str | None = None,
    next_wake_at: str | None = None,
    budget: dict[str, Any] | None = None,
    updated_at: str | None = None,
) -> None:
    """Write an agent status record: SQLite primary, YAML mirror.

    Creates .superharness/agents/ if it does not exist.
    """
    project_dir_str = str(project_dir)
    project_dir = Path(project_dir)
    when = updated_at or _now_utc()

    # SQLite primary — source of truth
    sqlite_ok = False
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import agent_runtime_status_dao
        conn = get_connection(project_dir_str)
        try:
            init_db(conn)
            agent_runtime_status_dao.upsert(
                conn,
                runtime=runtime,
                schema_version=SCHEMA_VERSION,
                liveness=liveness,
                active_task=active_task,
                next_wake_at=next_wake_at,
                budget=budget,
                updated_at=when,
            )
            conn.commit()
            sqlite_ok = True
        finally:
            conn.close()
    except Exception as e:
        logger.error("agent_status: SQLite SoT write failed — falling back to YAML crash dump: %s", e)

    # YAML mirror: skip only when SQLite succeeded AND sqlite_only mode is active.
    # If SQLite failed, write YAML regardless (C-DURABLE fallback).
    try:
        from superharness.engine.sqlite_only import is_sqlite_only
        if sqlite_ok and is_sqlite_only(project_dir=project_dir_str):
            return
    except Exception as e:
        logger.debug("agent_status: is_sqlite_only check failed, writing YAML mirror: %s", e)

    agents_dir = _agents_dir(project_dir)
    agents_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "schema_version": SCHEMA_VERSION,
        "runtime": runtime,
        "updated_at": when,
        "liveness": liveness,
        "active_task": active_task,
        "next_wake_at": next_wake_at,
        "budget": budget,
    }
    _status_path(project_dir, runtime).write_text(
        yaml.dump(record, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def _parse_record(data: dict[str, Any]) -> AgentStatusRecord | None:
    """Parse a raw YAML dict into an AgentStatusRecord, or return None."""
    try:
        runtime = str(data.get("runtime") or "")
        updated_at = str(data.get("updated_at") or "")
        if not runtime or not updated_at:
            return None
        return AgentStatusRecord(
            runtime=runtime,
            updated_at=updated_at,
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            liveness=str(data.get("liveness", "active")),
            active_task=data.get("active_task") or None,
            next_wake_at=data.get("next_wake_at") or None,
            budget=data.get("budget") or None,
        )
    except Exception as e:
        logger.warning("agent_status.py unexpected error: %s", e, exc_info=True)
        return None


def _dao_row_to_record(row) -> AgentStatusRecord:
    return AgentStatusRecord(
        runtime=row.runtime,
        updated_at=row.updated_at,
        schema_version=row.schema_version,
        liveness=row.liveness,
        active_task=row.active_task,
        next_wake_at=row.next_wake_at,
        budget=row.budget,
    )


def read_agent_status(
    project_dir: Path | str,
    runtime: str,
) -> AgentStatusRecord | None:
    """Read one runtime's status: prefer the FRESHER of SQLite vs YAML.

    C-DURABLE-READ (v11 fix): if a YAML crash dump is newer than the SQLite row
    (i.e. the last write failed SQLite but succeeded YAML), the YAML wins.
    Without this, stale SQLite data shadows fresh YAML crash dumps indefinitely.
    """
    # SQLite primary
    sqlite_rec: AgentStatusRecord | None = None
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import agent_runtime_status_dao
        conn = get_connection(str(project_dir))
        try:
            init_db(conn)
            row = agent_runtime_status_dao.get(conn, runtime)
        finally:
            conn.close()
        if row is not None:
            sqlite_rec = _dao_row_to_record(row)
    except Exception as e:
        logger.debug("agent_status: SQLite read failed: %s", e)

    # YAML check — prefer if mtime newer than SQLite row (sub-second-safe).
    path = _status_path(Path(project_dir), runtime)
    if not path.exists():
        return sqlite_rec
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}  # noqa: state-read — YAML compare-or-fallback when SQLite empty or stale
        if not isinstance(data, dict):
            return sqlite_rec
        yaml_rec = _parse_record(data)
    except Exception as e:
        logger.warning("agent_status.py unexpected error: %s", e, exc_info=True)
        return sqlite_rec

    if yaml_rec is None:
        return sqlite_rec
    if sqlite_rec is None:
        return yaml_rec
    if _yaml_newer_than(str(path), sqlite_rec.updated_at):
        return yaml_rec
    return sqlite_rec


def _yaml_newer_than(yaml_path: str, sqlite_iso_ts: str | None) -> bool:
    """Return True if yaml mtime > parsed SQLite ISO timestamp. See
    heartbeat_contract._yaml_newer_than for rationale (sub-second safety)."""
    import os as _os
    from datetime import datetime as _dt, timezone as _tz
    try:
        yaml_mtime = _os.path.getmtime(yaml_path)
        if not sqlite_iso_ts:
            return True
        sqlite_dt = _dt.strptime(sqlite_iso_ts.rstrip("Z"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_tz.utc)
        return yaml_mtime > sqlite_dt.timestamp()
    except Exception as e:
        logger.debug("agent_status._yaml_newer_than: %s", e)
        return False


def read_all_agent_statuses(
    project_dir: Path | str,
) -> dict[str, AgentStatusRecord]:
    """Read all agent statuses: merge SQLite (authoritative) with YAML (external runtimes).

    External agents may write status YAMLs directly without calling
    write_agent_status(). The merge ensures they remain visible even when
    SQLite already has native-runtime rows. SQLite wins for shared runtimes.

    Skips records that are corrupt or missing required fields — never raises.
    """
    # SQLite primary — collect into dict keyed by runtime
    result: dict[str, AgentStatusRecord] = {}
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import agent_runtime_status_dao
        conn = get_connection(str(project_dir))
        try:
            init_db(conn)
            rows = agent_runtime_status_dao.get_all(conn)
        finally:
            conn.close()
        for r in rows:
            result[r.runtime] = _dao_row_to_record(r)
    except Exception as e:
        logger.debug("agent_status: SQLite get_all failed: %s", e)

    # YAML scan — fills in runtimes not in SQLite AND prefers YAML when it is
    # newer than the SQLite row (C-DURABLE-READ: fresh crash dump > stale SQLite).
    agents_dir = _agents_dir(Path(project_dir))
    if not agents_dir.exists():
        return result

    for path in sorted(agents_dir.glob("*.status.yaml")):  # noqa: state-read — YAML scan: external runtimes + freshness compare
        runtime_name = path.name.removesuffix(".status.yaml")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}  # noqa: state-read — YAML scan: external runtimes + freshness compare
            if not isinstance(data, dict):
                continue
            record = _parse_record(data)
            if record is None:
                continue
            existing = result.get(runtime_name)
            if existing is None or _yaml_newer_than(str(path), existing.updated_at):
                result[runtime_name] = record
        except Exception as e:
            logger.warning("agent_status.py unexpected error: %s", e, exc_info=True)
            continue
    return result


# ---------------------------------------------------------------------------
# Staleness detection
# ---------------------------------------------------------------------------


def is_status_stale(record: AgentStatusRecord, stale_seconds: int = 120) -> bool:
    """Return True if the record's updated_at is older than stale_seconds.

    Treats unparseable timestamps as stale.
    """
    try:
        ts = record.updated_at.replace("Z", "+00:00")
        updated_dt = datetime.fromisoformat(ts)
        now_dt = datetime.now(timezone.utc)
        age = (now_dt - updated_dt).total_seconds()
        return age >= stale_seconds
    except (ValueError, AttributeError, TypeError):
        return True  # unparseable → treat as stale


def list_stale_agents(
    project_dir: Path | str,
    stale_seconds: int = 120,
) -> list[str]:
    """Return sorted list of runtime names whose status files are stale."""
    statuses = read_all_agent_statuses(project_dir)
    return sorted(
        runtime
        for runtime, record in statuses.items()
        if is_status_stale(record, stale_seconds)
    )


# ---------------------------------------------------------------------------
# Monitor-layer health projection
# ---------------------------------------------------------------------------


def agent_status_health(
    project_dir: Path | str,
    stale_seconds: int = 120,
) -> dict[str, Any]:
    """Return a health summary for all known agent runtimes.

    Never hardcodes runtime names — reads whatever is present in agents/.

    Returns::

        {
            "agents": {
                "<runtime>": {
                    "level": "ok" | "warn",
                    "message": str,
                    "liveness": str,
                    "active_task": str | None,
                    "age_seconds": int,
                }
            }
        }
    """
    statuses = read_all_agent_statuses(project_dir)
    agents: dict[str, Any] = {}

    for runtime, record in statuses.items():
        stale = is_status_stale(record, stale_seconds)
        try:
            ts = record.updated_at.replace("Z", "+00:00")
            updated_dt = datetime.fromisoformat(ts)
            age = int((datetime.now(timezone.utc) - updated_dt).total_seconds())
        except Exception as e:
            logger.warning("agent_status.py unexpected error: %s", e, exc_info=True)
            age = -1

        if stale:
            agents[runtime] = {
                "level": "warn",
                "message": (
                    f"Agent '{runtime}' heartbeat stale ({age}s ago) — may have crashed."
                    if age >= 0
                    else f"Agent '{runtime}' heartbeat timestamp unparseable."
                ),
                "liveness": record.liveness,
                "active_task": record.active_task,
                "age_seconds": age,
            }
        else:
            agents[runtime] = {
                "level": "ok",
                "message": f"Agent '{runtime}' heartbeat OK ({age}s ago).",
                "liveness": record.liveness,
                "active_task": record.active_task,
                "age_seconds": age,
            }

    return {"agents": agents}
