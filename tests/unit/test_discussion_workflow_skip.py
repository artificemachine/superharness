"""TDD: discussion-workflow tasks must skip auto-bootstrap and auto-peer-review.

Regression source — 2026-05-09 runaway:
  1. Codex CLI rejected gpt-5.3-codex (ChatGPT-account auth) → "unknown" classification.
  2. Identical-error loop fired auto_bootstrap on a discussion sub-task.
  3. Auto-bootstrap demoted task status to plan_proposed → outside discussion
     workflow's allowed set {todo, in_progress} → every subsequent dispatch hit
     "permanent block (lifecycle gate)".
  4. Auto-peer-review then fired on the (now plan_proposed) discussion sub-task,
     spawning 18+ gemini-cli inbox rows that all failed pre-flight (no AC by
     design — discussion rounds aren't implementations).

Both auto-flows must skip discussion-workflow tasks.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest


DISC_TASK_ID = "discuss-20260509T132148Z-test-fixture/round-1"
NORMAL_TASK_ID = "feat.regular-implementation"


def _make_project(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir(parents=True)
    (sh / "profile.yaml").write_text(
        "auto_approve_plans: true\nautonomy: ai_driven\n"
    )
    (sh / "inbox.yaml").write_text("items: []\n")
    return tmp_path


def _seed_task(project_dir: Path, task_id: str, status: str, owner: str = "claude-code", workflow: str | None = None) -> None:
    """Insert a task row directly into SQLite (bypasses contract YAML coupling)."""
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
        workflow=workflow,
    )
    tasks_dao.upsert(conn, row)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Auto-bootstrap must skip discussion sub-tasks
# ---------------------------------------------------------------------------

class TestAutoBootstrapSkipsDiscussion:
    def test_does_not_bootstrap_discussion_round_task(self, tmp_path):
        """Discussion rounds have no AC by design. Bootstrapping them sets
        status=plan_proposed, which is outside the discussion workflow's
        allowed set {todo, in_progress} — trapping the task forever.
        """
        from superharness.commands.inbox_watch import _auto_bootstrap_empty_tasks

        proj = _make_project(tmp_path)
        # Discussion sub-task escalated to waiting_input by some auto-flow
        _seed_task(proj, DISC_TASK_ID, status="waiting_input", workflow="discussion")

        bootstrapped = _auto_bootstrap_empty_tasks(str(proj))

        assert bootstrapped == 0, "Discussion sub-tasks must NOT be bootstrapped"

    def test_still_bootstraps_normal_implementation_task(self, tmp_path):
        """Don't break the existing bootstrap behavior for real impl tasks."""
        from superharness.commands.inbox_watch import _auto_bootstrap_empty_tasks

        proj = _make_project(tmp_path)
        _seed_task(proj, NORMAL_TASK_ID, status="waiting_input", workflow="implementation")

        bootstrapped = _auto_bootstrap_empty_tasks(str(proj))

        assert bootstrapped == 1


# ---------------------------------------------------------------------------
# Auto-peer-review must skip discussion sub-tasks
# ---------------------------------------------------------------------------

class TestAutoPeerReviewSkipsDiscussion:
    def test_does_not_peer_review_discussion_round_task(self, tmp_path):
        """Discussion rounds are already a multi-agent flow. Spawning peer-review
        rows for them creates the inbox flood we saw on 2026-05-09 (18+ failed
        gemini-cli rows that all hit gate 4 for missing AC).
        """
        from superharness.commands.inbox_watch import _auto_peer_approve_plans

        proj = _make_project(tmp_path)
        _seed_task(proj, DISC_TASK_ID, status="plan_proposed", workflow="discussion")

        # _auto_peer_approve_plans reads tasks via _load_tasks (contract.yaml),
        # so we must also seed the contract for the function to see the task
        # under the legacy dispatch path. With workflow inferred from the ID
        # regex, it should still skip even without the YAML mirror.
        import yaml as _yaml
        contract_file = proj / ".superharness" / "contract.yaml"
        contract_file.write_text(_yaml.safe_dump({
            "tasks": [{"id": DISC_TASK_ID, "status": "plan_proposed",
                       "owner": "claude-code", "workflow": "discussion"}]
        }))

        enqueued = _auto_peer_approve_plans(str(proj))

        assert enqueued == 0, "Discussion sub-tasks must NOT be peer-reviewed"

    def test_still_peer_reviews_normal_plan_proposed_task(self, tmp_path):
        """Don't break peer-review for normal implementation plans."""
        from superharness.commands.inbox_watch import _auto_peer_approve_plans

        proj = _make_project(tmp_path)
        _seed_task(proj, NORMAL_TASK_ID, status="plan_proposed", workflow="implementation")

        import yaml as _yaml
        contract_file = proj / ".superharness" / "contract.yaml"
        contract_file.write_text(_yaml.safe_dump({
            "tasks": [{"id": NORMAL_TASK_ID, "status": "plan_proposed",
                       "owner": "claude-code", "workflow": "implementation"}]
        }))

        enqueued = _auto_peer_approve_plans(str(proj))

        assert enqueued == 1
