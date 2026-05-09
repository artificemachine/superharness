"""Unified lifecycle reconciler — replaces 4 ad-hoc reconcilers with one rule table.

The data-driven rule table makes adding a new state-with-timeout a one-line change.
Each LifecycleRule declares:
  - state:           the source state to scan for
  - timeout_minutes: how long an entity may sit in this state before action
  - on_timeout:      what to do (fail, archive, revert)
  - revert_to:       for "revert" action, the destination state
  - skip_if_field:   if set, items with this field non-empty are exempt
                     (e.g. paused items with a manual `reason` field)
  - profile_key:     optional profile.yaml override for timeout_minutes
  - source:          "inbox" (scan inbox.yaml) or "contract" (scan contract.yaml)
  - timestamp_field: which field on the item carries the entry timestamp

Adding a new rule only requires adding a row to LIFECYCLE_RULES.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import yaml


@dataclass(frozen=True)
class LifecycleRule:
    state: str
    timeout_minutes: int
    on_timeout: Literal["fail", "archive", "revert"]
    source: Literal["inbox", "contract"]
    timestamp_field: str
    revert_to: str | None = None
    skip_if_field: str | None = None
    profile_key: str | None = None  # profile.yaml override key
    fail_reason_template: str = (
        "{state} timeout ({age_minutes}m >= {limit_minutes}m limit)"
    )


LIFECYCLE_RULES: list[LifecycleRule] = [
    LifecycleRule(
        state="paused",
        timeout_minutes=30,
        on_timeout="fail",
        source="inbox",
        timestamp_field="paused_at",
        skip_if_field="reason",
        profile_key="paused_timeout_minutes",
    ),
    LifecycleRule(
        state="review_requested",
        timeout_minutes=120,
        on_timeout="revert",
        revert_to="report_ready",
        source="contract",
        timestamp_field="review_requested_at",
        skip_if_field="escalated_to",  # iter 7: leave escalated reviews alone
        profile_key="review_timeout_minutes",
    ),
    LifecycleRule(
        state="in_progress",
        timeout_minutes=180,
        on_timeout="archive",
        source="contract",
        timestamp_field="updated_at",
        profile_key="in_progress_timeout_minutes",
    ),
    LifecycleRule(
        state="waiting_input",
        timeout_minutes=480,  # 8 hours
        on_timeout="fail",
        source="contract",
        timestamp_field="updated_at",
        profile_key="waiting_input_timeout_minutes",
        fail_reason_template=(
            "waiting_input timeout ({age_minutes}m >= {limit_minutes}m) — "
            "no human response received"
        ),
    ),
    LifecycleRule(
        state="report_ready",
        timeout_minutes=1440,  # 24 hours
        on_timeout="archive",
        source="contract",
        timestamp_field="report_ready_at",
        profile_key="report_ready_timeout_minutes",
        fail_reason_template=(
            "report_ready timeout ({age_minutes}m >= {limit_minutes}m) — "
            "no review activity"
        ),
    ),
    LifecycleRule(
        state="todo",
        timeout_minutes=120,  # 2 hours
        on_timeout="archive",
        source="contract",
        timestamp_field="created_at",
        profile_key="todo_timeout_minutes",
        fail_reason_template=(
            "todo timeout ({age_minutes}m >= {limit_minutes}m) — "
            "task was never dispatched"
        ),
    ),
]

# Non-terminal states that are eligible for deadline enforcement.
# Terminal/archived states are excluded because deadline has already passed or
# the task was intentionally closed.
_DEADLINE_ELIGIBLE_STATES = frozenset({
    "todo", "plan_proposed", "plan_approved", "in_progress",
    "report_ready", "review_requested", "review_passed", "review_failed",
    "pending_user_approval", "waiting_input", "pr_open", "blocked",
    "paused", "stopped",
})


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_profile(project_dir: str) -> dict:
    path = os.path.join(project_dir, ".superharness", "profile.yaml")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f.read()) or {}
    except Exception:
        return {}


def _effective_timeout(rule: LifecycleRule, profile: dict) -> int:
    if rule.profile_key:
        try:
            return int(profile.get(rule.profile_key, rule.timeout_minutes))
        except (ValueError, TypeError):
            pass
    return rule.timeout_minutes


def _age_minutes(ts_str: str) -> float | None:
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    now = datetime.now(timezone.utc)
    return (now - ts).total_seconds() / 60


def _apply_action(item: dict, rule: LifecycleRule, age: float, limit: int) -> bool:
    """Mutate item in-place per rule. Returns True if a change was made."""
    reason = rule.fail_reason_template.format(
        state=rule.state, age_minutes=int(age), limit_minutes=limit
    )
    now = _now_utc_str()
    if rule.on_timeout == "fail":
        item["status"] = "failed"
        item["failed_reason"] = reason
        item["failed_at"] = now
        return True
    if rule.on_timeout == "archive":
        item["status"] = "archived"
        item["archived_at"] = now
        item["archived_reason"] = reason
        return True
    if rule.on_timeout == "revert":
        if not rule.revert_to:
            return False
        item["status"] = rule.revert_to
        item.pop(rule.timestamp_field, None)
        return True
    return False


def _scan_inbox(project_dir: str, rules: list[LifecycleRule], profile: dict) -> int:
    from superharness.engine import state_reader, state_writer
    
    try:
        items = state_reader.get_inbox_items(project_dir)
    except Exception:
        return 0

    changed = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        original_status = item.get("status")
        for rule in rules:
            if rule.source != "inbox":
                continue
            if original_status != rule.state:
                continue
            if rule.skip_if_field and item.get(rule.skip_if_field):
                continue
            age = _age_minutes(item.get(rule.timestamp_field, ""))
            if age is None:
                continue
            limit = _effective_timeout(rule, profile)
            if limit <= 0:
                continue
            if age >= limit:
                if _apply_action(item, rule, age, limit):
                    new_status = item["status"]
                    item_id = str(item.get("id", ""))
                    print(
                        f"lifecycle: inbox item {item_id} "
                        f"{rule.state} → {new_status} ({int(age)}m >= {limit}m)"
                    )
                    # Write update via state_writer — pass only lifecycle-relevant fields
                    _lifecycle_fields = {
                        k: v for k, v in item.items()
                        if k in ("failed_reason", "failed_at", "archived_reason", "archived_at")
                    }
                    state_writer.set_inbox_status(project_dir, item_id, new_status, **_lifecycle_fields)
                    changed += 1
                    break  # one rule per item per pass

    return changed


def _scan_contract(project_dir: str, rules: list[LifecycleRule], profile: dict) -> int:
    from superharness.engine import state_reader, state_writer

    try:
        tasks = state_reader.get_tasks(project_dir)
    except Exception:
        return 0

    changed = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        original_status = task.get("status")
        for rule in rules:
            if rule.source != "contract":
                continue
            if original_status != rule.state:
                continue
            if rule.skip_if_field and task.get(rule.skip_if_field):
                continue
            age = _age_minutes(task.get(rule.timestamp_field, ""))
            if age is None:
                continue
            limit = _effective_timeout(rule, profile)
            if limit <= 0:
                continue
            if age >= limit:
                if _apply_action(task, rule, age, limit):
                    new_status = task["status"]
                    task_id = str(task.get("id", ""))
                    print(
                        f"lifecycle: task {task_id} "
                        f"{rule.state} → {new_status} ({int(age)}m >= {limit}m)"
                    )
                    # Write update via state_writer — pass only lifecycle-relevant fields
                    _lifecycle_fields = {
                        k: v for k, v in task.items()
                        if k in ("failed_reason", "failed_at", "archived_reason", "archived_at")
                    }
                    # System-driven transition (timeout): bypass the
                    # interactive transition graph since e.g. in_progress→archived
                    # is not a legal user move but is the whole point of
                    # the reconciler.
                    state_writer.set_task_status(
                        project_dir, task_id, new_status,
                        from_status=original_status, force=True,
                        **_lifecycle_fields,
                    )
                    changed += 1
                    break

    return changed


def _check_deadlines(project_dir: str, profile: dict) -> int:
    """Enforce per-task deadline_minutes on non-terminal tasks.

    Checks if a task's created_at exceeds its deadline_minutes value.
    Tasks with deadline_minutes unset or <= 0 are skipped.

    Returns count of tasks failed due to deadline expiry.
    """
    from superharness.engine import state_reader, state_writer

    # Allow profile override for a project-wide default deadline
    default_deadline = None
    try:
        default_deadline = int(profile.get("default_deadline_minutes", 0))
    except (ValueError, TypeError):
        pass

    try:
        tasks = state_reader.get_tasks(project_dir)
    except Exception:
        return 0

    changed = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status", ""))
        if status not in _DEADLINE_ELIGIBLE_STATES:
            continue

        # Per-task deadline takes precedence over project default
        deadline = None
        raw_deadline = task.get("deadline_minutes")
        if raw_deadline is not None:
            try:
                deadline = int(raw_deadline)
            except (ValueError, TypeError):
                pass
        if not deadline:
            deadline = default_deadline
        if not deadline or deadline <= 0:
            continue

        age = _age_minutes(task.get("created_at", ""))
        if age is None:
            continue
        if age < deadline:
            continue

        task_id = str(task.get("id", ""))
        reason = (
            f"deadline exceeded ({int(age)}m elapsed >= {deadline}m limit) — "
            f"task was in status '{status}'"
        )
        print(
            f"lifecycle: task {task_id} "
            f"deadline exceeded ({int(age)}m >= {deadline}m) → failed"
        )

        state_writer.set_task_status(
            project_dir, task_id, "failed",
            from_status=status, force=True,
            failed_reason=reason,
            failed_at=_now_utc_str(),
        )
        changed += 1

    return changed


def reconcile_lifecycle(project_dir: str) -> int:
    """Run all lifecycle rules + deadline enforcement.

    Returns total count of items/tasks changed.
    """
    profile = _load_profile(project_dir)
    inbox_rules = [r for r in LIFECYCLE_RULES if r.source == "inbox"]
    contract_rules = [r for r in LIFECYCLE_RULES if r.source == "contract"]
    return (
        _scan_inbox(project_dir, inbox_rules, profile)
        + _scan_contract(project_dir, contract_rules, profile)
        + _check_deadlines(project_dir, profile)
    )
