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
]


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
    from superharness.engine.sqlite_only import is_sqlite_only

    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")

    if is_sqlite_only():
        # SQLite-only: read from SQLite, apply rules, write back.
        from dataclasses import asdict
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        db_path = os.path.join(project_dir, ".superharness", "state.sqlite3")
        if not os.path.isfile(db_path):
            return 0
        try:
            conn = get_connection(project_dir)
            try:
                init_db(conn)
                rows = inbox_dao.get_all(conn)
                items = [asdict(r) for r in rows]
            finally:
                conn.close()
        except Exception:
            return 0
    changed = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        for rule in rules:
            if rule.source != "inbox":
                continue
            if item.get("status") != rule.state:
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
                    print(
                        f"lifecycle: inbox item {item.get('id', '?')} "
                        f"{rule.state} → {item['status']} ({int(age)}m >= {limit}m)"
                    )
                    changed += 1
                    break  # one rule per item per pass

    if changed:
        from superharness.engine.sqlite_only import is_sqlite_only

        if is_sqlite_only():
            # SQLite-only: just mirror to SQLite, skip YAML file write.
            from superharness.engine.state_writer import mirror_inbox_item_dict

            for item in items:
                if isinstance(item, dict):
                    mirror_inbox_item_dict(project_dir, item)
    return changed


def _scan_contract(project_dir: str, rules: list[LifecycleRule], profile: dict) -> int:
    from superharness.engine.sqlite_only import is_sqlite_only

    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")

    if is_sqlite_only():
        # SQLite-only: read from SQLite, apply rules, write back.
        from dataclasses import asdict
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        db_path = os.path.join(project_dir, ".superharness", "state.sqlite3")
        if not os.path.isfile(db_path):
            return 0
        try:
            conn = get_connection(project_dir)
            try:
                init_db(conn)
                rows = tasks_dao.get_all(conn)
                tasks = [asdict(r) for r in rows]
            finally:
                conn.close()
        except Exception:
            return 0
    changed = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for rule in rules:
            if rule.source != "contract":
                continue
            if task.get("status") != rule.state:
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
                    print(
                        f"lifecycle: task {task.get('id', '?')} "
                        f"{rule.state} → {task['status']} ({int(age)}m >= {limit}m)"
                    )
                    changed += 1
                    break

    if changed:
        from superharness.engine.sqlite_only import is_sqlite_only

        if is_sqlite_only():
            # SQLite-only: just mirror to SQLite, skip YAML file write.
            from superharness.engine.state_writer import mirror_task_dict

            for task in tasks:
                if isinstance(task, dict):
                    mirror_task_dict(project_dir, task)
    return changed


def reconcile_lifecycle(project_dir: str) -> int:
    """Run all lifecycle rules. Returns total count of items/tasks changed."""
    profile = _load_profile(project_dir)
    inbox_rules = [r for r in LIFECYCLE_RULES if r.source == "inbox"]
    contract_rules = [r for r in LIFECYCLE_RULES if r.source == "contract"]
    return _scan_inbox(project_dir, inbox_rules, profile) + _scan_contract(
        project_dir, contract_rules, profile
    )
