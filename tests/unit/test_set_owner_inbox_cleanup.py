"""TDD: shux task set-owner must actually clean up inbox items.

Bug filed 2026-05-09 (docs/BUG-set-owner-inbox-cleanup.md): the cleanup
block at commands/task.py:483 imports `_load_items` and `_write_items`
from `engine/inbox`, which were removed in the YAML→SQLite migration.
The ImportError surfaces at runtime, the "Reassigned" line still prints,
and inbox rows for the old owner stay orphaned.

Fix: replace the YAML-based cleanup with a SQLite-backed equivalent
using inbox_dao. Mark active rows for the old owner as 'canceled'
(preserve audit trail; do not delete) and SIGTERM live pids.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest


TASK_ID = "feat.test-set-owner"


def _make_project(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir(parents=True)
    (sh / "profile.yaml").write_text("auto_approve_plans: false\nautonomy: ai_driven\n")
    (sh / "inbox.yaml").write_text("items: []\n")
    # Minimal contract.yaml — set_owner reads/writes it
    import yaml as _yaml
    (sh / "contract.yaml").write_text(_yaml.safe_dump({
        "tasks": [{
            "id": TASK_ID,
            "title": "test",
            "owner": "claude-code",
            "status": "in_progress",
            "workflow": "implementation",
            "project_path": str(tmp_path),
        }],
    }))
    return tmp_path


def _seed_inbox_row(project_dir: Path, task_id: str, *, target_agent: str,
                    status: str = "pending", item_id: str | None = None) -> str:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao
    import uuid

    if item_id is None:
        item_id = f"test-{uuid.uuid4().hex[:8]}"
    conn = get_connection(str(project_dir))
    init_db(conn)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    inbox_dao.enqueue(
        conn,
        id=item_id,
        task_id=task_id,
        target_agent=target_agent,
        priority=2,
        max_retries=3,
        project_path=str(project_dir),
        plan_only=False,
        now=now,
    )
    if status != "pending":
        conn.execute("UPDATE inbox SET status=? WHERE id=?", (status, item_id))
    conn.commit()
    conn.close()
    return item_id


def _seed_task_in_db(project_dir: Path, task_id: str, owner: str = "claude-code") -> None:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    conn = get_connection(str(project_dir))
    init_db(conn)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = tasks_dao.TaskRow(
        id=task_id, title=f"test {task_id}", owner=owner, status="in_progress",
        effort="medium", project_path=str(project_dir), development_method=None,
        acceptance_criteria=[], test_types=[], out_of_scope=[],
        definition_of_done=[], context=None, tdd=None, version=1,
        created_at=now, updated_at=now,
        plan_proposed_at=None, plan_approved_at=None, in_progress_at=now,
        report_ready_at=None, review_requested_at=None,
        done_at=None, cancelled_at=None, blocked_by=[],
        verified=False, verified_at=None, verified_by=None, deadline_minutes=None,
        failed_at=None, stopped_at=None, failed_reason=None,
        archived_at=None, archived_reason=None, model_tier=None, pause_reason=None,
        workflow="implementation",
    )
    tasks_dao.upsert(conn, row)
    conn.commit()
    conn.close()


def _inbox_status_for(project_dir: Path, item_id: str) -> str:
    from superharness.engine.db import get_connection
    conn = get_connection(str(project_dir))
    try:
        cur = conn.execute("SELECT status FROM inbox WHERE id=?", (item_id,))
        row = cur.fetchone()
        return row[0] if row else "missing"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSetOwnerInboxCleanup:
    def test_cancels_active_inbox_rows_for_old_owner(self, tmp_path):
        """A pending row for the old owner must be canceled when reassigning."""
        from superharness.commands.task import set_owner

        proj = _make_project(tmp_path)
        _seed_task_in_db(proj, TASK_ID, owner="claude-code")
        item_id = _seed_inbox_row(proj, TASK_ID, target_agent="claude-code", status="pending")

        contract_file = str(proj / ".superharness" / "contract.yaml")
        rc = set_owner(contract_file, TASK_ID, "codex-cli")

        assert rc == 0
        assert _inbox_status_for(proj, item_id) == "canceled", (
            "the pending row for the old owner must be canceled, not left active"
        )

    def test_does_not_touch_unrelated_rows(self, tmp_path):
        """A row for a different task or already-terminal must not change."""
        from superharness.commands.task import set_owner

        proj = _make_project(tmp_path)
        _seed_task_in_db(proj, TASK_ID, owner="claude-code")
        _seed_task_in_db(proj, "other-task", owner="claude-code")  # FK requires task row
        unrelated = _seed_inbox_row(
            proj, "other-task", target_agent="claude-code", status="pending",
            item_id="other-1",
        )
        terminal = _seed_inbox_row(
            proj, TASK_ID, target_agent="claude-code", status="done",
            item_id="terminal-1",
        )

        contract_file = str(proj / ".superharness" / "contract.yaml")
        set_owner(contract_file, TASK_ID, "codex-cli")

        assert _inbox_status_for(proj, unrelated) == "pending"
        assert _inbox_status_for(proj, terminal) == "done"

    def test_does_not_cancel_rows_for_new_owner(self, tmp_path):
        """Rows already targeted at the new owner should be left alone."""
        from superharness.commands.task import set_owner

        proj = _make_project(tmp_path)
        _seed_task_in_db(proj, TASK_ID, owner="claude-code")
        new_owner_row = _seed_inbox_row(
            proj, TASK_ID, target_agent="codex-cli", status="pending",
            item_id="new-owner-1",
        )

        contract_file = str(proj / ".superharness" / "contract.yaml")
        set_owner(contract_file, TASK_ID, "codex-cli")

        assert _inbox_status_for(proj, new_owner_row) == "pending"

    def test_does_not_raise_importerror(self, tmp_path):
        """The original bug surface: ImportError leaked from the cleanup
        block. After the fix, the function must complete cleanly even with
        no inbox rows present."""
        from superharness.commands.task import set_owner

        proj = _make_project(tmp_path)
        _seed_task_in_db(proj, TASK_ID, owner="claude-code")

        contract_file = str(proj / ".superharness" / "contract.yaml")
        # Should not raise
        rc = set_owner(contract_file, TASK_ID, "codex-cli")
        assert rc == 0
