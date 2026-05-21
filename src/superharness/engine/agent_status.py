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
    """Write (or overwrite) an agent status file for the given runtime.

    Creates .superharness/agents/ if it does not exist.
    """
    project_dir = Path(project_dir)
    agents_dir = _agents_dir(project_dir)
    agents_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "schema_version": SCHEMA_VERSION,
        "runtime": runtime,
        "updated_at": updated_at or _now_utc(),
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


def read_agent_status(
    project_dir: Path | str,
    runtime: str,
) -> AgentStatusRecord | None:
    """Read the status file for one runtime.  Returns None if absent or corrupt."""
    path = _status_path(Path(project_dir), runtime)
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return None
        return _parse_record(data)
    except Exception as e:
        logger.warning("agent_status.py unexpected error: %s", e, exc_info=True)
        return None


def read_all_agent_statuses(
    project_dir: Path | str,
) -> dict[str, AgentStatusRecord]:
    """Read all agent status files.  Discovers runtimes dynamically.

    Skips files that are corrupt or missing required fields — never raises.
    """
    agents_dir = _agents_dir(Path(project_dir))
    if not agents_dir.exists():
        return {}

    result: dict[str, AgentStatusRecord] = {}
    for path in sorted(agents_dir.glob("*.status.yaml")):
        runtime_name = path.name.removesuffix(".status.yaml")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                continue
            record = _parse_record(data)
            if record is not None:
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
