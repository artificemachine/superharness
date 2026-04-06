"""
Heartbeat contract v1 — runtime-agnostic agent status schema.

File paths:
  .superharness/watcher.heartbeat.yaml            — watcher heartbeat
  .superharness/agents/{agent_id}.heartbeat.yaml  — per-agent heartbeats

Schema (YAML):
  schema_version: "1"
  agent_id: "watcher"
  runtime: "native" | "codex-cli" | "external" | ...
  pid: 12345                # optional
  status: "idle" | "running" | "dispatching" | "stale"
  active_task: null         # or task ID string
  next_wake_at: null        # or UTC ISO 8601
  written_at: "2026-04-05T14:30:45Z"
  budget:                   # optional
    tokens_used: 0
    tokens_limit: null
    cost_usd: 0.0
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

SCHEMA_VERSION = "1"
STALE_SECONDS_DEFAULT = 120


@dataclass
class AgentBudget:
    tokens_used: int = 0
    tokens_limit: Optional[int] = None
    cost_usd: float = 0.0


@dataclass
class AgentHeartbeat:
    schema_version: str = SCHEMA_VERSION
    agent_id: str = "unknown"
    runtime: str = "native"
    pid: Optional[int] = None
    status: str = "idle"
    active_task: Optional[str] = None
    next_wake_at: Optional[str] = None
    written_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    budget: Optional[AgentBudget] = None


def heartbeat_path(project_dir: str, agent_id: str = "watcher") -> str:
    """Return canonical file path for an agent heartbeat."""
    if agent_id == "watcher":
        return os.path.join(project_dir, ".superharness", "watcher.heartbeat.yaml")
    agents_dir = os.path.join(project_dir, ".superharness", "agents")
    return os.path.join(agents_dir, f"{agent_id}.heartbeat.yaml")


def write_heartbeat(project_dir: str, heartbeat: AgentHeartbeat) -> None:
    """Write an AgentHeartbeat to its canonical path."""
    import yaml  # type: ignore

    path = heartbeat_path(project_dir, heartbeat.agent_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data: dict = {
        "schema_version": heartbeat.schema_version,
        "agent_id": heartbeat.agent_id,
        "runtime": heartbeat.runtime,
        "status": heartbeat.status,
        "written_at": heartbeat.written_at,
    }
    if heartbeat.pid is not None:
        data["pid"] = heartbeat.pid
    if heartbeat.active_task is not None:
        data["active_task"] = heartbeat.active_task
    if heartbeat.next_wake_at is not None:
        data["next_wake_at"] = heartbeat.next_wake_at
    if heartbeat.budget is not None:
        data["budget"] = {
            "tokens_used": heartbeat.budget.tokens_used,
            "tokens_limit": heartbeat.budget.tokens_limit,
            "cost_usd": heartbeat.budget.cost_usd,
        }
    with open(path, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False)


def read_heartbeat(path: str) -> Optional[AgentHeartbeat]:
    """Read an AgentHeartbeat from a YAML file. Returns None if unreadable/invalid."""
    import yaml  # type: ignore

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return None
        budget: Optional[AgentBudget] = None
        raw_budget = data.get("budget")
        if isinstance(raw_budget, dict):
            budget = AgentBudget(
                tokens_used=int(raw_budget.get("tokens_used") or 0),
                tokens_limit=raw_budget.get("tokens_limit"),
                cost_usd=float(raw_budget.get("cost_usd") or 0.0),
            )
        return AgentHeartbeat(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            agent_id=str(data.get("agent_id", "unknown")),
            runtime=str(data.get("runtime", "native")),
            pid=data.get("pid"),
            status=str(data.get("status", "idle")),
            active_task=data.get("active_task"),
            next_wake_at=data.get("next_wake_at"),
            written_at=str(data.get("written_at", "")),
            budget=budget,
        )
    except Exception:
        return None


def is_stale(heartbeat: AgentHeartbeat, stale_seconds: int = STALE_SECONDS_DEFAULT) -> bool:
    """Return True if heartbeat written_at is older than stale_seconds."""
    try:
        hb_dt = datetime.fromisoformat(heartbeat.written_at.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - hb_dt).total_seconds() >= stale_seconds
    except Exception:
        return True


def age_seconds(heartbeat: AgentHeartbeat) -> int:
    """Return age of heartbeat in seconds, or -1 if written_at is unparseable."""
    try:
        hb_dt = datetime.fromisoformat(heartbeat.written_at.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - hb_dt).total_seconds())
    except Exception:
        return -1


def list_agent_heartbeats(project_dir: str) -> list[AgentHeartbeat]:
    """Return all valid heartbeats in a project: watcher first, then per-agent."""
    results: list[AgentHeartbeat] = []
    watcher_hb = read_heartbeat(heartbeat_path(project_dir, "watcher"))
    if watcher_hb is not None:
        results.append(watcher_hb)
    agents_dir = os.path.join(project_dir, ".superharness", "agents")
    if os.path.isdir(agents_dir):
        for fname in sorted(os.listdir(agents_dir)):
            if fname.endswith(".heartbeat.yaml"):
                hb = read_heartbeat(os.path.join(agents_dir, fname))
                if hb is not None:
                    results.append(hb)
    return results
