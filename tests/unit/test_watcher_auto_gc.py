"""Tests for watcher auto-gc — periodic inbox reconciliation in watcher loop."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml


def _make_project(tmp_path: Path, tasks: list[dict], inbox_items: list[dict], profile: dict | None = None) -> Path:
    harness = tmp_path / ".superharness"
    harness.mkdir(parents=True)
    (harness / "handoffs").mkdir()
    (harness / "ledger.md").write_text("")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    contract = {
        "id": "test", "created": "2026-04-07", "created_by": "owner",
        "status": "active", "tasks": tasks,
    }
    (harness / "contract.yaml").write_text(yaml.dump(contract, default_flow_style=False))
    (harness / "inbox.yaml").write_text(yaml.dump(inbox_items, default_flow_style=False))
    if profile:
        (harness / "profile.yaml").write_text(yaml.dump(profile, default_flow_style=False))
    return tmp_path


def _load_inbox(project: Path) -> list[dict]:
    return yaml.safe_load((project / ".superharness" / "inbox.yaml").read_text()) or []


@pytest.fixture(autouse=True)
def _reset_cycle_counter():
    from superharness.commands.inbox_watch import _watcher_cycle_count
    _watcher_cycle_count[0] = 0
    yield
    _watcher_cycle_count[0] = 0


def test_watcher_gc_runs_in_run_scripts(tmp_path):
    """_run_scripts calls inbox gc reconciliation during the watcher cycle."""
    from superharness.commands.inbox_watch import _run_scripts, _watcher_cycle_count

    project = _make_project(tmp_path,
        tasks=[{"id": "t-1", "title": "done", "owner": "claude-code", "status": "done"}],
        inbox_items=[{
            "id": "item-1", "task": "t-1", "to": "claude-code",
            "status": "failed", "created_at": "2026-04-07T00:00:00Z",
        }],
        profile={"gc_interval_cycles": 1},
    )
    # Run one watcher cycle — gc should reconcile the failed item
    _run_scripts(
        str(project), target="claude-code", print_only=True,
        non_interactive=True, codex_bypass=False, launcher_timeout=0,
        recover_timeout_minutes=3, recover_action="stale",
    )
    items = _load_inbox(project)
    item = next(i for i in items if i["id"] == "item-1")
    assert item["status"] == "done"


def test_watcher_gc_skips_active_items(tmp_path):
    """Watcher gc does not touch active inbox items."""
    from superharness.commands.inbox_watch import _run_scripts

    project = _make_project(tmp_path,
        tasks=[{"id": "t-1", "title": "done", "owner": "claude-code", "status": "done"}],
        inbox_items=[{
            "id": "item-1", "task": "t-1", "to": "claude-code",
            "status": "running", "created_at": "2026-04-07T00:00:00Z",
        }],
    )
    _run_scripts(
        str(project), target="claude-code", print_only=True,
        non_interactive=True, codex_bypass=False, launcher_timeout=0,
        recover_timeout_minutes=3, recover_action="stale",
    )
    items = _load_inbox(project)
    item = next(i for i in items if i["id"] == "item-1")
    assert item["status"] == "running"


def test_watcher_gc_configurable_interval(tmp_path):
    """GC only runs every N cycles based on gc_interval_cycles in profile."""
    from superharness.commands.inbox_watch import _run_gc_if_due

    project = _make_project(tmp_path,
        tasks=[{"id": "t-1", "title": "done", "owner": "claude-code", "status": "done"}],
        inbox_items=[{
            "id": "item-1", "task": "t-1", "to": "claude-code",
            "status": "failed", "created_at": "2026-04-07T00:00:00Z",
        }],
        profile={"gc_interval_cycles": 3},
    )

    # Cycle 1 and 2: should not run gc
    ran = _run_gc_if_due(str(project), cycle_count=1)
    assert not ran
    ran = _run_gc_if_due(str(project), cycle_count=2)
    assert not ran
    items = _load_inbox(project)
    assert items[0]["status"] == "failed"

    # Cycle 3: should run gc
    ran = _run_gc_if_due(str(project), cycle_count=3)
    assert ran
    items = _load_inbox(project)
    assert items[0]["status"] == "done"
