"""Pydantic v2 models for SuperHarness protocol YAML types.

Provides runtime schema validation for the 5 protocol YAML types:
Contract, Handoff, Heartbeat, Profile, and Inbox.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    todo = "todo"
    plan_proposed = "plan_proposed"
    plan_approved = "plan_approved"
    in_progress = "in_progress"
    report_ready = "report_ready"
    review_passed = "review_passed"
    done = "done"
    failed = "failed"
    blocked = "blocked"


class InboxStatus(str, Enum):
    pending = "pending"
    launched = "launched"
    running = "running"
    done = "done"
    failed = "failed"
    stale = "stale"
    paused = "paused"


class ModelTier(str, Enum):
    mini = "mini"
    standard = "standard"
    max = "max"


class SubtaskStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    failed = "failed"


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


class Subtask(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    model_tier: ModelTier
    owner: str
    estimated_tokens: int
    estimated_cost_usd: float
    status: SubtaskStatus = SubtaskStatus.pending
    actual_tokens: Optional[int] = None
    actual_cost_usd: Optional[float] = None
    model_used: Optional[str] = None


class ContractTask(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    title: str
    owner: str
    status: TaskStatus
    project_path: Optional[str] = None
    acceptance_criteria: Optional[list[str]] = None
    test_types: Optional[list[str]] = None
    tdd: Optional[dict] = None
    blocked_by: Optional[str] = None
    dependency: Optional[str] = None
    summary: Optional[str] = None
    verified: Optional[bool] = None
    verified_at: Optional[str] = None
    verified_by: Optional[str] = None
    deadline_minutes: Optional[int] = None
    review_requested_at: Optional[str] = None
    subtasks: list[Subtask] = []
    estimated_cost_usd: Optional[float] = None
    budget_usd: Optional[float] = None


class Contract(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    created: Union[str, date, datetime]
    created_by: str
    status: Literal["draft", "active", "closed", "archived"]
    goal: Optional[str] = None
    tasks: list[ContractTask] = []
    decisions: list[Any] = []
    failures: list[Any] = []


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------


class Handoff(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    contract_id: Optional[str] = None
    task: str
    from_: str = Field(alias="from")
    to: str
    status: str
    summary: Optional[str] = None
    scope: list[str] = []
    commands: list[str] = []
    acceptance: list[str] = []
    risks: list[str] = []
    artifacts: list[str] = []


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


class HeartbeatCheck(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    description: str
    interval_minutes: int
    enabled: bool = True


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="allow")

    checks: list[HeartbeatCheck] = []


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


class Profile(BaseModel):
    model_config = ConfigDict(extra="allow")

    project_name: str
    created: Union[str, date]
    autonomy: Literal["autonomous", "supervised", "approval-gated"] = "approval-gated"
    primary_agent: Literal["claude-code", "codex-cli"]
    stack: str
    repo: Optional[Literal["github", "gitlab", "bitbucket", "other"]] = None
    ci: Optional[Literal["github-actions", "gitlab-ci", "jenkins", "circleci", "none"]] = None
    team_size: Optional[Literal["solo", "small", "team"]] = None
    existing_harness: list[str] = []
    watcher: bool = False
    vault_path: Optional[str] = None
    default_model: Optional[Literal["mini", "standard", "max"]] = None
    default_effort: Optional[Literal["low", "medium", "high"]] = None


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------


class InboxItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    to: str
    task: str
    project: str
    status: InboxStatus
    priority: int = 2
    retry_count: int = 0
    max_retries: int = 3
    created_at: str
    launched_at: Optional[str] = None
    done_at: Optional[str] = None
    failed_at: Optional[str] = None
    stale_at: Optional[str] = None
    failed_reason: Optional[str] = None
    stale_reason: Optional[str] = None
    pid: Optional[int] = None
    running_at: Optional[str] = None
    stopped_at: Optional[str] = None


class InboxDoc(BaseModel):
    """Wrapper for inbox.yaml which is a bare list at the top level."""

    model_config = ConfigDict(extra="allow")

    items: list[InboxItem]
