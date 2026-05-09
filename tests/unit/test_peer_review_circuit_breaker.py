"""TDD: auto-peer-review must not loop on tasks with recent peer-review failures.

Regression source — 2026-05-08 feat-rules-dashboard runaway:
  19 peer-review rows spawned in 4m40s, all permanent_block (lifecycle gate).
  Same pattern hit a discussion task on 2026-05-09 (already fixed via
  workflow-skip; this is the general circuit breaker for ALL workflows).

Cause: _auto_peer_approve_plans considers only pending/launched/running/paused
inbox rows when checking "is this task already being processed". Failed rows
don't count, so when a peer-review row fails fast (~14s) the next watcher
cycle sees no active row and queues another. Unbounded.

Fix: skip enqueue when there's any peer-review row for this task that
failed within the last 15 minutes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


TASK_ID = "feat.test-circuit-breaker"


def _make_project(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir(parents=True)
    (sh / "profile.yaml").write_text(
        "auto_approve_plans: true\nautonomy: ai_driven\n"
    )
    (sh / "inbox.yaml").write_text("items: []\n")
    return tmp_path


def _seed_task(project_dir: Path, task_id: str, status: str, owner: str = "claude-code") -> None:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    conn = get_connection(str(project_dir))
    init_db(conn)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = tasks_dao.TaskRow(
        id=task_id,
        title=f"Test task {task_id}",
        owner=owner,
        status=status,
        effort="medium",
        project_path=str(project_dir),
        development_method=None,
        acceptance_criteria=[],
        test_types=[],
        out_of_scope=[],
        definition_of_done=[],
        context=None,
        tdd=None,
        version=1,
        created_at=now,
        updated_at=now,
        plan_proposed_at=None,
        plan_approved_at=None,
        in_progress_at=None,
        report_ready_at=None,
        review_requested_at=None,
        done_at=None,
        cancelled_at=None,
        blocked_by=[],
        verified=False,
        verified_at=None,
        verified_by=None,
        deadline_minutes=None,
        failed_at=None,
        stopped_at=None,
        failed_reason=None,
        archived_at=None,
        archived_reason=None,
        model_tier=None,
        pause_reason=None,
        workflow="implementation",
    )
    tasks_dao.upsert(conn, row)
    conn.commit()
    conn.close()


def _seed_failed_peer_review_row(project_dir: Path, task_id: str, age_minutes: int) -> None:
    """Insert a failed peer-review inbox row failed N minutes ago."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao
    import uuid

    conn = get_connection(str(project_dir))
    init_db(conn)
    failed_at = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    item_id = f"peer-review-{task_id.replace('.', '-')}-{uuid.uuid4().hex[:8]}"
    # Enqueue then mark failed by direct SQL — inbox_dao doesn't expose a "set
    # failed at arbitrary timestamp" helper.
    inbox_dao.enqueue(
        conn,
        id=item_id,
        task_id=task_id,
        target_agent="gemini-cli",
        priority=1,
        max_retries=2,
        project_path=str(project_dir),
        plan_only=True,
        now=failed_at,
    )
    conn.execute(
        "UPDATE inbox SET status='failed', failed_at=?, "
        "failed_reason='permanent block (lifecycle gate)' WHERE id=?",
        (failed_at, item_id),
    )
    conn.commit()
    conn.close()


def _seed_contract(project_dir: Path, task_id: str, status: str = "plan_proposed") -> None:
    import yaml as _yaml
    contract_file = project_dir / ".superharness" / "contract.yaml"
    contract_file.write_text(_yaml.safe_dump({
        "tasks": [{"id": task_id, "status": status,
                   "owner": "claude-code", "workflow": "implementation"}]
    }))


# ---------------------------------------------------------------------------
# Circuit breaker: skip when a peer-review row failed recently
# ---------------------------------------------------------------------------

class TestPeerReviewCircuitBreaker:
    def test_skips_when_recent_peer_review_failure_exists(self, tmp_path):
        """If any peer-review row for this task failed in the last 15 min,
        do not queue another. This stops the runaway loop where each failed
        row vanishes from the active set and unblocks the next enqueue.
        """
        from superharness.commands.inbox_watch import _auto_peer_approve_plans

        proj = _make_project(tmp_path)
        _seed_task(proj, TASK_ID, status="plan_proposed")
        _seed_contract(proj, TASK_ID)
        _seed_failed_peer_review_row(proj, TASK_ID, age_minutes=2)

        enqueued = _auto_peer_approve_plans(str(proj))

        assert enqueued == 0, "must skip when recent peer-review failure exists"

    def test_enqueues_when_failure_is_older_than_window(self, tmp_path):
        """A failure older than the cooldown window should not block forever.
        Operator may have fixed the underlying issue; allow a retry.
        """
        from superharness.commands.inbox_watch import _auto_peer_approve_plans

        proj = _make_project(tmp_path)
        _seed_task(proj, TASK_ID, status="plan_proposed")
        _seed_contract(proj, TASK_ID)
        # Older than the 15-minute window
        _seed_failed_peer_review_row(proj, TASK_ID, age_minutes=30)

        enqueued = _auto_peer_approve_plans(str(proj))

        assert enqueued == 1, "must enqueue once cooldown has elapsed"

    def test_enqueues_when_no_prior_peer_review_failures(self, tmp_path):
        """No history → normal behavior (don't break the happy path)."""
        from superharness.commands.inbox_watch import _auto_peer_approve_plans

        proj = _make_project(tmp_path)
        _seed_task(proj, TASK_ID, status="plan_proposed")
        _seed_contract(proj, TASK_ID)

        enqueued = _auto_peer_approve_plans(str(proj))

        assert enqueued == 1
