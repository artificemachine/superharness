"""TDD: three follow-ups to the v1.54.6 peer-review circuit breaker.

A. Auto-bootstrap is workflow-aware: skip any workflow where plan_proposed
   isn't in allowed_statuses_for_workflow(). The discussion-only carve-out
   in v1.54.5 was too narrow — same trap exists for any non-implementation
   workflow that doesn't include plan_proposed in its dispatch set.

B. operator_memory observe-and-promote: after observing the same
   `unknown:<sha256>` failure signature N times (default 3), classify
   future occurrences as permanent_block instead of unknown. Closes the
   feedback loop between memory and dispatch decisions.

C. Auto-archive stopped tasks idle >7 days. Pure hygiene — keeps the
   Active Tasks list honest and lets `shux contract` show only live work.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _make_project(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir(parents=True)
    (sh / "profile.yaml").write_text("auto_approve_plans: true\nautonomy: ai_driven\n")
    (sh / "inbox.yaml").write_text("items: []\n")
    return tmp_path


def _seed_task(project_dir: Path, task_id: str, *, status: str,
               workflow: str | None = None, owner: str = "claude-code",
               stopped_at: str | None = None) -> None:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    conn = get_connection(str(project_dir))
    init_db(conn)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = tasks_dao.TaskRow(
        id=task_id, title=f"Test {task_id}", owner=owner, status=status,
        effort="medium", project_path=str(project_dir), development_method=None,
        acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None, version=1,
        created_at=now, updated_at=now,
        plan_proposed_at=None, plan_approved_at=None, in_progress_at=None,
        report_ready_at=None, review_requested_at=None,
        done_at=None, cancelled_at=None, blocked_by=[],
        verified=False, verified_at=None, verified_by=None, deadline_minutes=None,
        failed_at=None, stopped_at=stopped_at, failed_reason=None,
        archived_at=None, archived_reason=None, model_tier=None, pause_reason=None,
        workflow=workflow,
    )
    tasks_dao.upsert(conn, row)
    # tasks_dao.upsert doesn't include workflow/stopped_at in its INSERT;
    # force them via direct UPDATE so the test can drive workflow-aware paths.
    if workflow is not None:
        conn.execute("UPDATE tasks SET workflow=? WHERE id=?", (workflow, task_id))
    if stopped_at:
        conn.execute("UPDATE tasks SET stopped_at=? WHERE id=?", (stopped_at, task_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Fix A: workflow-aware auto-bootstrap
# ---------------------------------------------------------------------------

class TestAutoBootstrapWorkflowAware:
    def test_skips_quick_workflow_task(self, tmp_path):
        """quick workflow has plan_proposed NOT in allowed dispatch set
        ({todo, in_progress, report_ready, failed, stopped}). Bootstrap
        demoting to plan_proposed would trap the task — same shape as the
        discussion bug.
        """
        from superharness.commands.inbox_watch import _auto_bootstrap_empty_tasks

        proj = _make_project(tmp_path)
        _seed_task(proj, "task.quick", status="waiting_input", workflow="quick")

        bootstrapped = _auto_bootstrap_empty_tasks(str(proj))

        assert bootstrapped == 0, "quick-workflow tasks must NOT be bootstrapped (plan_proposed isn't in allowed dispatch set)"

    def test_skips_review_workflow_task(self, tmp_path):
        """review workflow's allowed set is {todo, in_progress, review_requested, review_failed}."""
        from superharness.commands.inbox_watch import _auto_bootstrap_empty_tasks

        proj = _make_project(tmp_path)
        _seed_task(proj, "task.review", status="waiting_input", workflow="review")

        bootstrapped = _auto_bootstrap_empty_tasks(str(proj))

        assert bootstrapped == 0

    def test_skips_note_workflow_task(self, tmp_path):
        """note workflow's allowed set is {todo, in_progress, failed, stopped}."""
        from superharness.commands.inbox_watch import _auto_bootstrap_empty_tasks

        proj = _make_project(tmp_path)
        _seed_task(proj, "task.note", status="waiting_input", workflow="note")

        bootstrapped = _auto_bootstrap_empty_tasks(str(proj))

        assert bootstrapped == 0

    def test_still_bootstraps_implementation_task(self, tmp_path):
        """implementation workflow includes plan_proposed in allowed_set —
        bootstrap demotion is safe and useful here."""
        from superharness.commands.inbox_watch import _auto_bootstrap_empty_tasks

        proj = _make_project(tmp_path)
        _seed_task(proj, "task.impl", status="waiting_input", workflow="implementation")

        bootstrapped = _auto_bootstrap_empty_tasks(str(proj))

        assert bootstrapped == 1


# ---------------------------------------------------------------------------
# Fix B: operator_memory observe-and-promote
# ---------------------------------------------------------------------------

class TestOperatorMemoryPromotion:
    def test_promotes_after_threshold_observations(self, tmp_path):
        """After observing the same unknown:<sha256> signature N times,
        promote_unknown_to_permanent_block returns 'permanent_block'."""
        from superharness.engine.operator_memory import OperatorMemory

        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True)
        db_path = str(sh / "state.sqlite3")
        om = OperatorMemory(db_path)
        om.ensure_table()

        sig = "unknown:abc123def4567890"
        # Seed once, then observe 3 more times → should promote on 4th observation
        om.record_new(sig, "test snippet")
        for _ in range(3):
            result = om.observe_and_promote(sig)
            # First two observations: still unknown
            # Third observation (total = 4 with the seed): promote

        # Final state: hit_count + miss_count >= 3 → promoted
        assert result == "permanent_block", f"expected promotion, got {result!r}"

    def test_does_not_promote_below_threshold(self, tmp_path):
        from superharness.engine.operator_memory import OperatorMemory

        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True)
        db_path = str(sh / "state.sqlite3")
        om = OperatorMemory(db_path)
        om.ensure_table()

        sig = "unknown:newpattern0000000"
        om.record_new(sig, "test")
        result = om.observe_and_promote(sig)  # 1 observation, below threshold

        assert result is None

    def test_seeds_new_signature_on_first_observe(self, tmp_path):
        """If the signature isn't in memory yet, observe_and_promote seeds it."""
        from superharness.engine.operator_memory import OperatorMemory

        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True)
        db_path = str(sh / "state.sqlite3")
        om = OperatorMemory(db_path)
        om.ensure_table()

        sig = "unknown:freshsignature00"
        result = om.observe_and_promote(sig, error_snippet="some failure")

        assert result is None  # First seen — don't promote yet
        assert om.find_pattern(sig) is not None  # but seed it

    def test_increments_observation_counters(self, tmp_path):
        from superharness.engine.operator_memory import OperatorMemory

        sh = tmp_path / ".superharness"
        sh.mkdir(parents=True)
        db_path = str(sh / "state.sqlite3")
        om = OperatorMemory(db_path)
        om.ensure_table()

        sig = "unknown:counted00000000"
        om.record_new(sig, "test")
        om.observe_and_promote(sig)
        om.observe_and_promote(sig)

        mem = om.find_pattern(sig)
        # Counter goes up; whether hit or miss is implementation detail
        assert mem["miss_count"] + mem["hit_count"] >= 2


# ---------------------------------------------------------------------------
# Fix C: auto-archive stopped >7 days
# ---------------------------------------------------------------------------

class TestAutoArchiveStoppedTasks:
    def test_archives_task_stopped_more_than_7d(self, tmp_path):
        """A task in status='stopped' with stopped_at > 7 days ago should be
        auto-archived by the lifecycle reconciler."""
        from superharness.engine.lifecycle_rules import LIFECYCLE_RULES

        # First-class assertion: a rule for state='stopped' exists
        stopped_rules = [r for r in LIFECYCLE_RULES if r.state == "stopped"]
        assert len(stopped_rules) == 1, "must have exactly one stopped-state rule"
        rule = stopped_rules[0]
        assert rule.on_timeout == "archive"
        assert rule.timeout_minutes >= 10080, "stopped timeout must be >= 7 days"
        assert rule.timestamp_field == "stopped_at"

    def test_does_not_archive_recently_stopped_task(self, tmp_path):
        """Reconciler must not touch a task stopped less than 7 days ago."""
        from superharness.engine.lifecycle_rules import (
            LIFECYCLE_RULES, _scan_contract as reconcile_contract,
        )
        rule = next(r for r in LIFECYCLE_RULES if r.state == "stopped")

        proj = _make_project(tmp_path)
        recent = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_task(proj, "task.recent-stop", status="stopped",
                   workflow="implementation", stopped_at=recent)

        # Run the reconciler with just the stopped rule
        archived_count = reconcile_contract(str(proj), [rule], profile={})

        assert archived_count == 0

    def test_archives_old_stopped_task(self, tmp_path):
        """Reconciler archives a task stopped >7 days ago."""
        from superharness.engine.lifecycle_rules import (
            LIFECYCLE_RULES, _scan_contract as reconcile_contract,
        )
        rule = next(r for r in LIFECYCLE_RULES if r.state == "stopped")

        proj = _make_project(tmp_path)
        old = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _seed_task(proj, "task.old-stop", status="stopped",
                   workflow="implementation", stopped_at=old)

        archived_count = reconcile_contract(str(proj), [rule], profile={})

        assert archived_count == 1
