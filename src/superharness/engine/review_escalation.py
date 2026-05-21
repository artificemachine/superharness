"""Review escalation chain — replaces simple timeout-revert with reviewer routing.

Iter 2's lifecycle rule for review_requested reverts to report_ready after
the timeout. That works but loses context: if a peer reviewer never responded,
we want to try the next one in the chain, not silently retry the same person.

This module adds a per-task `review_chain` ordered list of reviewers plus a
`review_chain_index` cursor. On each timeout:
  1. If chain has more entries, advance index, set review_target to next.
  2. If chain exhausted (or absent), set escalated_to=operator. Operator sees
     this in the dashboard with a clear flag.

The lifecycle rule for review_requested is replaced by this richer behavior
when the watcher tick runs both reconcilers.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import yaml

import logging
logger = logging.getLogger(__name__)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_minutes(ts_str: str) -> float | None:
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return (datetime.now(timezone.utc) - ts).total_seconds() / 60


def _load_profile(project_dir: str) -> dict:
    path = os.path.join(project_dir, ".superharness", "profile.yaml")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f.read()) or {}
    except Exception as e:
        logger.warning("review_escalation.py unexpected error: %s", e, exc_info=True)
        return {}


def escalate_stale_reviews(project_dir: str, timeout_minutes: int | None = None) -> int:
    """Advance stale reviews along their review_chain, or escalate to operator.

    Returns count of tasks updated.
    """
    profile = _load_profile(project_dir)
    if timeout_minutes is None:
        try:
            timeout_minutes = int(profile.get("review_timeout_minutes", 120))
        except (ValueError, TypeError):
            timeout_minutes = 120

    if timeout_minutes <= 0:
        return 0

    from superharness.engine import state_reader
    try:
        tasks = state_reader.get_tasks(project_dir)
    except Exception as e:
        logger.warning("review_escalation.py unexpected error: %s", e, exc_info=True)
        return 0

    changed = 0

    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("status") != "review_requested":
            continue
        # Skip already-escalated tasks
        if task.get("escalated_to"):
            continue
        ts = task.get("review_requested_at") or task.get("updated_at") or ""
        age = _age_minutes(ts)
        if age is None or age < timeout_minutes:
            continue

        chain = task.get("review_chain") or []
        idx = int(task.get("review_chain_index", 0) or 0)

        if isinstance(chain, list) and idx + 1 < len(chain):
            # Advance to next reviewer
            new_idx = idx + 1
            task["review_chain_index"] = new_idx
            task["review_target"] = chain[new_idx]
            task["review_requested_at"] = _now_utc()  # reset timer for next reviewer
            print(
                f"review-escalation: {task.get('id')} "
                f"reviewer {idx} ({chain[idx]}) timed out, advancing to {new_idx} ({chain[new_idx]})"
            )
            changed += 1
        else:
            # Chain exhausted (or absent): escalate to operator
            task["escalated_to"] = "operator"
            task["escalated_at"] = _now_utc()
            print(
                f"review-escalation: {task.get('id')} "
                f"chain exhausted (or absent), escalating to operator"
            )
            changed += 1

    if changed:
        from superharness.engine.sqlite_only import is_sqlite_only

        if is_sqlite_only():
            # SQLite-only: mirror directly, skip YAML file write.
            from superharness.engine.state_writer import mirror_task_dict
            for task in tasks:
                if isinstance(task, dict):
                    mirror_task_dict(project_dir, task)
        else:
            try:
                with open(contract_file, "w", encoding="utf-8") as f:
                    yaml.dump(doc, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                from superharness.engine.state_writer import mirror_task_dict
                for task in tasks:
                    if isinstance(task, dict):
                        mirror_task_dict(project_dir, task)
            except Exception as e:
                import sys
                print(f"review-escalation: failed to write contract: {e}", file=sys.stderr)
                return 0

    return changed
