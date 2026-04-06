"""Tests for always-on auto-dispatch: watcher enqueues plan_approved tasks automatically.

TDD RED phase — all tests must fail before implementation starts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_contract(project: Path, tasks: list[dict]) -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "contract.yaml").write_text(
        yaml.dump({"id": "test-contract", "tasks": tasks}, default_flow_style=False)
    )


def _write_inbox(project: Path, items: list[dict]) -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "inbox.yaml").write_text(
        yaml.dump(items, default_flow_style=False)
    )


def _read_inbox(project: Path) -> list[dict]:
    f = project / ".superharness" / "inbox.yaml"
    if not f.exists():
        return []
    return yaml.safe_load(f.read_text()) or []


def _write_profile(project: Path, auto_dispatch: bool) -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "profile.yaml").write_text(
        yaml.dump({"auto_dispatch": auto_dispatch}, default_flow_style=False)
    )


# ---------------------------------------------------------------------------
# Test 1 — auto-enqueue plan_approved task
# ---------------------------------------------------------------------------

def test_auto_dispatch_enqueues_plan_approved(tmp_path):
    """Watcher auto-enqueues plan_approved contract task when auto_dispatch=True."""
    from superharness.commands.inbox_watch import auto_enqueue_approved

    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, [
        {"id": "task-1", "owner": "claude-code", "status": "plan_approved"},
    ])
    _write_inbox(project, [])
    _write_profile(project, auto_dispatch=True)

    added = auto_enqueue_approved(str(project))

    assert added == 1, f"Expected 1 item enqueued, got {added}"
    items = _read_inbox(project)
    assert len(items) == 1
    assert items[0]["task"] == "task-1"
    assert items[0]["status"] == "pending"
    assert items[0]["to"] == "claude-code"


# ---------------------------------------------------------------------------
# Test 2 — idempotent: running twice doesn't duplicate
# ---------------------------------------------------------------------------

def test_auto_dispatch_idempotent(tmp_path):
    """Running auto_enqueue_approved twice on the same project adds no duplicates."""
    from superharness.commands.inbox_watch import auto_enqueue_approved

    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, [
        {"id": "task-2", "owner": "claude-code", "status": "plan_approved"},
    ])
    _write_inbox(project, [])
    _write_profile(project, auto_dispatch=True)

    auto_enqueue_approved(str(project))
    added = auto_enqueue_approved(str(project))

    assert added == 0, "Second call should add nothing (already pending)"
    items = _read_inbox(project)
    assert len(items) == 1, "Inbox should still have exactly 1 item"


# ---------------------------------------------------------------------------
# Test 3 — other statuses are skipped
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["todo", "plan_proposed", "in_progress", "report_ready", "done", "review_failed"])
def test_auto_dispatch_skips_other_statuses(tmp_path, status):
    """Only plan_approved tasks are auto-enqueued; all other statuses are ignored."""
    from superharness.commands.inbox_watch import auto_enqueue_approved

    project = tmp_path / f"proj-{status}"
    project.mkdir()
    _write_contract(project, [
        {"id": "task-x", "owner": "claude-code", "status": status},
    ])
    _write_inbox(project, [])
    _write_profile(project, auto_dispatch=True)

    added = auto_enqueue_approved(str(project))

    assert added == 0, f"Status '{status}' should not be auto-enqueued, got {added}"
    assert _read_inbox(project) == []


# ---------------------------------------------------------------------------
# Test 4 — off by default
# ---------------------------------------------------------------------------

def test_auto_dispatch_off_by_default(tmp_path):
    """No auto-enqueue when auto_dispatch is absent from profile.yaml."""
    from superharness.commands.inbox_watch import auto_enqueue_approved

    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, [
        {"id": "task-3", "owner": "claude-code", "status": "plan_approved"},
    ])
    _write_inbox(project, [])
    # No profile written — missing auto_dispatch key

    added = auto_enqueue_approved(str(project))

    assert added == 0, "Should not enqueue when auto_dispatch not configured"
    assert _read_inbox(project) == []


def test_auto_dispatch_off_when_false(tmp_path):
    """No auto-enqueue when auto_dispatch=False in profile.yaml."""
    from superharness.commands.inbox_watch import auto_enqueue_approved

    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, [
        {"id": "task-4", "owner": "claude-code", "status": "plan_approved"},
    ])
    _write_inbox(project, [])
    _write_profile(project, auto_dispatch=False)

    added = auto_enqueue_approved(str(project))

    assert added == 0, "Should not enqueue when auto_dispatch=False"


# ---------------------------------------------------------------------------
# Test 5 — skip if active inbox entry already exists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("active_status", ["pending", "launched", "running", "paused"])
def test_auto_dispatch_skips_if_active_inbox_entry(tmp_path, active_status):
    """Do not re-enqueue a task that already has an active inbox entry."""
    from superharness.commands.inbox_watch import auto_enqueue_approved

    project = tmp_path / f"proj-{active_status}"
    project.mkdir()
    _write_contract(project, [
        {"id": "task-5", "owner": "claude-code", "status": "plan_approved"},
    ])
    _write_inbox(project, [
        {"id": "existing-item", "task": "task-5", "to": "claude-code",
         "status": active_status, "priority": 2, "retry_count": 0, "max_retries": 3},
    ])
    _write_profile(project, auto_dispatch=True)

    added = auto_enqueue_approved(str(project))

    assert added == 0, f"Should not enqueue when inbox already has '{active_status}' entry"
    items = _read_inbox(project)
    assert len(items) == 1, "Inbox should remain unchanged"


def test_auto_dispatch_reenqueues_after_done(tmp_path):
    """A task may be re-enqueued if the only inbox entry is done or failed."""
    from superharness.commands.inbox_watch import auto_enqueue_approved

    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, [
        {"id": "task-6", "owner": "claude-code", "status": "plan_approved"},
    ])
    _write_inbox(project, [
        {"id": "old-item", "task": "task-6", "to": "claude-code",
         "status": "done", "priority": 2, "retry_count": 0, "max_retries": 3},
    ])
    _write_profile(project, auto_dispatch=True)

    added = auto_enqueue_approved(str(project))

    assert added == 1, "Should re-enqueue after previous run completed (done)"


# ---------------------------------------------------------------------------
# Test 6 — respects blocked_by via _deps_satisfied
# ---------------------------------------------------------------------------

def test_auto_dispatch_respects_blocked_by(tmp_path):
    """Tasks with unresolved blocked_by deps are not auto-enqueued."""
    from superharness.commands.inbox_watch import auto_enqueue_approved

    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, [
        {"id": "dep-task", "owner": "claude-code", "status": "in_progress"},
        {"id": "task-7", "owner": "claude-code", "status": "plan_approved",
         "blocked_by": "dep-task"},
    ])
    _write_inbox(project, [])
    _write_profile(project, auto_dispatch=True)

    added = auto_enqueue_approved(str(project))

    assert added == 0, "Should not enqueue task with unresolved blocked_by"
    assert _read_inbox(project) == []


def test_auto_dispatch_enqueues_when_dep_done(tmp_path):
    """Tasks whose blocked_by dep is done ARE auto-enqueued."""
    from superharness.commands.inbox_watch import auto_enqueue_approved

    project = tmp_path / "proj"
    project.mkdir()
    _write_contract(project, [
        {"id": "dep-task", "owner": "claude-code", "status": "done"},
        {"id": "task-8", "owner": "claude-code", "status": "plan_approved",
         "blocked_by": "dep-task"},
    ])
    _write_inbox(project, [])
    _write_profile(project, auto_dispatch=True)

    added = auto_enqueue_approved(str(project))

    assert added == 1, "Should enqueue when all blocked_by deps are done"


# ---------------------------------------------------------------------------
# Test 7 — config key readable via shux config
# ---------------------------------------------------------------------------

def test_config_auto_dispatch_key(tmp_path):
    """auto_dispatch can be set and read via the config system."""
    from superharness.commands.config import get_config_value, set_config_value

    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()

    set_config_value(str(project), "auto_dispatch", "true")
    val = get_config_value(str(project), "auto_dispatch")

    assert val in (True, "true", "True"), f"Expected truthy, got {val!r}"


# ---------------------------------------------------------------------------
# Test 8 — watcher tick calls auto_enqueue_approved when enabled
# ---------------------------------------------------------------------------

def test_watcher_tick_calls_auto_enqueue(tmp_path, monkeypatch):
    """The watcher main loop calls auto_enqueue_approved on each tick."""
    from superharness.commands import inbox_watch

    calls = []

    def _fake_auto_enqueue(project_dir: str) -> int:
        calls.append(project_dir)
        return 0

    monkeypatch.setattr(inbox_watch, "auto_enqueue_approved", _fake_auto_enqueue)

    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    (project / ".superharness" / "inbox.yaml").write_text("[]\n")
    (project / ".superharness" / "contract.yaml").write_text("id: c\ntasks: []\n")
    _write_profile(project, auto_dispatch=True)

    # Run a single tick (not the full loop)
    inbox_watch.run_once(str(project), to="both", non_interactive=True,
                         recover_timeout_minutes=3, recover_action="retry",
                         launcher_timeout=0)

    assert len(calls) == 1, "auto_enqueue_approved should be called once per tick"
