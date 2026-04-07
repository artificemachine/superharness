"""RED phase tests for feat.inbox-gc — reconcile stale inbox items against contract."""
from __future__ import annotations

import yaml
from pathlib import Path

import pytest


def _make_project(tmp_path: Path, tasks: list[dict], inbox_items: list[dict]) -> Path:
    """Create a minimal project with contract and inbox."""
    harness = tmp_path / ".superharness"
    harness.mkdir(parents=True)
    (harness / "handoffs").mkdir()
    (harness / "ledger.md").write_text("")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")

    contract = {
        "id": "test",
        "created": "2026-04-07",
        "created_by": "owner",
        "status": "active",
        "tasks": tasks,
    }
    (harness / "contract.yaml").write_text(yaml.dump(contract, default_flow_style=False))
    (harness / "inbox.yaml").write_text(yaml.dump(inbox_items, default_flow_style=False))
    return tmp_path


def _load_inbox(tmp_path: Path) -> list[dict]:
    return yaml.safe_load((tmp_path / ".superharness" / "inbox.yaml").read_text())


# ── Core GC behavior ──


def test_gc_marks_stopped_inbox_done_when_task_done(tmp_path):
    """Inbox item with status=stopped should become done when contract task is done."""
    from superharness.commands.inbox_gc import run_gc

    project = _make_project(tmp_path,
        tasks=[{"id": "t-1", "title": "test", "owner": "claude-code", "status": "done"}],
        inbox_items=[{
            "id": "item-1", "task": "t-1", "to": "claude-code",
            "status": "stopped", "created_at": "2026-04-07T00:00:00Z",
        }],
    )
    result = run_gc(project)
    assert result["reconciled"] == 1

    items = _load_inbox(tmp_path)
    assert items[0]["status"] == "done"


def test_gc_marks_failed_inbox_done_when_task_done(tmp_path):
    """Inbox item with status=failed should become done when contract task is done."""
    from superharness.commands.inbox_gc import run_gc

    project = _make_project(tmp_path,
        tasks=[{"id": "t-1", "title": "test", "owner": "claude-code", "status": "done"}],
        inbox_items=[{
            "id": "item-1", "task": "t-1", "to": "claude-code",
            "status": "failed", "created_at": "2026-04-07T00:00:00Z",
            "failed_reason": "launcher exited with code 1",
        }],
    )
    result = run_gc(project)
    assert result["reconciled"] == 1

    items = _load_inbox(tmp_path)
    assert items[0]["status"] == "done"


def test_gc_marks_paused_inbox_done_when_task_done(tmp_path):
    """Inbox item with status=paused should become done when contract task is done."""
    from superharness.commands.inbox_gc import run_gc

    project = _make_project(tmp_path,
        tasks=[{"id": "t-1", "title": "test", "owner": "claude-code", "status": "done"}],
        inbox_items=[{
            "id": "item-1", "task": "t-1", "to": "claude-code",
            "status": "paused", "created_at": "2026-04-07T00:00:00Z",
            "pause_reason": "dirty_worktree_requires_user_confirmation",
        }],
    )
    result = run_gc(project)
    assert result["reconciled"] == 1

    items = _load_inbox(tmp_path)
    assert items[0]["status"] == "done"


def test_gc_marks_stale_inbox_done_when_task_done(tmp_path):
    """Inbox item with status=stale should become done when contract task is done."""
    from superharness.commands.inbox_gc import run_gc

    project = _make_project(tmp_path,
        tasks=[{"id": "t-1", "title": "test", "owner": "claude-code", "status": "done"}],
        inbox_items=[{
            "id": "item-1", "task": "t-1", "to": "claude-code",
            "status": "stale", "created_at": "2026-04-07T00:00:00Z",
        }],
    )
    result = run_gc(project)
    assert result["reconciled"] == 1

    items = _load_inbox(tmp_path)
    assert items[0]["status"] == "done"


def test_gc_dry_run_no_changes(tmp_path):
    """--dry-run shows stale items without modifying inbox."""
    from superharness.commands.inbox_gc import run_gc

    project = _make_project(tmp_path,
        tasks=[{"id": "t-1", "title": "test", "owner": "claude-code", "status": "done"}],
        inbox_items=[{
            "id": "item-1", "task": "t-1", "to": "claude-code",
            "status": "stopped", "created_at": "2026-04-07T00:00:00Z",
        }],
    )
    result = run_gc(project, dry_run=True)
    assert result["reconciled"] == 0
    assert result["would_reconcile"] == 1

    items = _load_inbox(tmp_path)
    assert items[0]["status"] == "stopped"  # unchanged


def test_gc_skips_active_items(tmp_path):
    """GC does not touch pending/launched/running inbox items even if task is done."""
    from superharness.commands.inbox_gc import run_gc

    project = _make_project(tmp_path,
        tasks=[{"id": "t-1", "title": "test", "owner": "claude-code", "status": "done"}],
        inbox_items=[{
            "id": "item-1", "task": "t-1", "to": "claude-code",
            "status": "pending", "created_at": "2026-04-07T00:00:00Z",
        }],
    )
    result = run_gc(project)
    assert result["reconciled"] == 0

    items = _load_inbox(tmp_path)
    assert items[0]["status"] == "pending"


def test_gc_skips_items_for_non_done_tasks(tmp_path):
    """GC does not touch inbox items when the contract task is not done."""
    from superharness.commands.inbox_gc import run_gc

    project = _make_project(tmp_path,
        tasks=[{"id": "t-1", "title": "test", "owner": "claude-code", "status": "report_ready"}],
        inbox_items=[{
            "id": "item-1", "task": "t-1", "to": "claude-code",
            "status": "failed", "created_at": "2026-04-07T00:00:00Z",
        }],
    )
    result = run_gc(project)
    assert result["reconciled"] == 0


def test_gc_multiple_items_mixed(tmp_path):
    """GC reconciles multiple stale items, skips active ones."""
    from superharness.commands.inbox_gc import run_gc

    project = _make_project(tmp_path,
        tasks=[
            {"id": "t-1", "title": "done task", "owner": "claude-code", "status": "done"},
            {"id": "t-2", "title": "active task", "owner": "claude-code", "status": "in_progress"},
        ],
        inbox_items=[
            {"id": "item-1", "task": "t-1", "to": "claude-code", "status": "stopped", "created_at": "2026-04-07T00:00:00Z"},
            {"id": "item-2", "task": "t-1", "to": "claude-code", "status": "failed", "created_at": "2026-04-07T00:00:00Z"},
            {"id": "item-3", "task": "t-2", "to": "claude-code", "status": "paused", "created_at": "2026-04-07T00:00:00Z"},
        ],
    )
    result = run_gc(project)
    assert result["reconciled"] == 2  # item-1 and item-2

    items = _load_inbox(tmp_path)
    assert items[0]["status"] == "done"
    assert items[1]["status"] == "done"
    assert items[2]["status"] == "paused"  # task not done, skip


def test_gc_writes_ledger_entry(tmp_path):
    """GC appends a ledger entry for each reconciled item."""
    from superharness.commands.inbox_gc import run_gc

    project = _make_project(tmp_path,
        tasks=[{"id": "t-1", "title": "test", "owner": "claude-code", "status": "done"}],
        inbox_items=[{
            "id": "item-1", "task": "t-1", "to": "claude-code",
            "status": "stopped", "created_at": "2026-04-07T00:00:00Z",
        }],
    )
    run_gc(project)

    ledger = (tmp_path / ".superharness" / "ledger.md").read_text()
    assert "item-1" in ledger
    assert "gc" in ledger.lower()
