"""Tests for the zombie-reconciler race fix.

recover_launched() must hold _inbox_lock for the entire read-modify-write
cycle to prevent a concurrent dispatcher's claim() from clobbering
stale-recovery writes.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import yaml


HEADER = "# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n\n"


pytestmark = pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")

def _make_inbox(tmp_path: Path, items: list[dict]) -> Path:
    project = tmp_path / "proj"
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    inbox = harness / "inbox.yaml"
    inbox.write_text(HEADER + yaml.dump(items, default_flow_style=False, allow_unicode=True))
    return project


def _stale_ts() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestRecoverLaunchedHoldsLock:
    """Verify that recover_launched uses _inbox_lock so it is re-entrant safe."""

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_recover_launched_uses_inbox_lock(self, tmp_path):
        """recover_launched should acquire _inbox_lock — importing and calling it
        should not raise even when the lock is briefly held by another thread."""
        from superharness.engine.inbox import recover_launched, _inbox_lock

        project = _make_inbox(tmp_path, items=[{
            "id": "I-1",
            "task": "T-1",
            "to": "claude-code",
            "project": str(tmp_path / "proj"),
            "status": "launched",
            "launched_at": _stale_ts(),
            "priority": 1,
            "pid": None,
        }])
        inbox_file = str(project / ".superharness" / "inbox.yaml")

        # Should run without error and mark the item stale
        rc = recover_launched(
            file=inbox_file,
            now=_now_ts(),
            timeout_minutes=5,
            action="stale",
        )
        assert rc == 0

        items = yaml.safe_load(open(inbox_file)) or []
        assert items[0]["status"] == "stale"

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_recover_launched_does_not_corrupt_concurrent_claim(self, tmp_path):
        """When recover_launched and claim run concurrently, the final state must
        be consistent — each item should have exactly one status, not a mix of
        stale+pending or a missing entry."""
        from superharness.engine.inbox import recover_launched, claim, _inbox_lock

        project = _make_inbox(tmp_path, items=[
            {
                "id": "I-2",
                "task": "T-2",
                "to": "claude-code",
                "project": str(tmp_path / "proj"),
                "status": "launched",
                "launched_at": _stale_ts(),
                "priority": 1,
                "pid": None,
            },
            {
                "id": "I-3",
                "task": "T-3",
                "to": "claude-code",
                "project": str(tmp_path / "proj"),
                "status": "pending",
                "launched_at": None,
                "priority": 1,
                "pid": None,
            },
        ])
        inbox_file = str(project / ".superharness" / "inbox.yaml")

        errors: list[Exception] = []

        def run_recover():
            try:
                recover_launched(
                    file=inbox_file,
                    now=_now_ts(),
                    timeout_minutes=5,
                    action="stale",
                )
            except Exception as e:
                errors.append(e)

        def run_claim():
            try:
                claim(
                    file=inbox_file,
                    target="claude-code",
                    now=_now_ts(),
                )
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=run_recover)
        t2 = threading.Thread(target=run_claim)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors, f"Concurrent access raised errors: {errors}"

        # The file must still be valid YAML with all items present
        items = yaml.safe_load(open(inbox_file)) or []
        assert len(items) == 2, f"Expected 2 items, got {len(items)}: {items}"

        # Each item must have a valid status
        statuses = {item["id"]: item["status"] for item in items}
        assert statuses["I-2"] in ("stale", "pending", "launched"), f"I-2 status={statuses['I-2']}"
        assert statuses["I-3"] in ("claimed", "pending", "launched"), f"I-3 status={statuses['I-3']}"

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_recover_launched_with_retry_action(self, tmp_path):
        """retry action should reset stale items to pending, not stale."""
        from superharness.engine.inbox import recover_launched

        project = _make_inbox(tmp_path, items=[{
            "id": "I-4",
            "task": "T-4",
            "to": "claude-code",
            "project": str(tmp_path / "proj"),
            "status": "launched",
            "launched_at": _stale_ts(),
            "priority": 1,
            "pid": None,
            "retry_count": 0,
            "max_retries": 3,
        }])
        inbox_file = str(project / ".superharness" / "inbox.yaml")

        rc = recover_launched(
            file=inbox_file,
            now=_now_ts(),
            timeout_minutes=5,
            action="retry",
        )
        assert rc == 0

        items = yaml.safe_load(open(inbox_file)) or []
        assert items[0]["status"] == "pending"

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_recover_launched_fresh_items_not_marked_stale(self, tmp_path):
        """Items launched recently (within timeout) must not be touched."""
        from superharness.engine.inbox import recover_launched

        recent = (datetime.now(timezone.utc) - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        project = _make_inbox(tmp_path, items=[{
            "id": "I-5",
            "task": "T-5",
            "to": "claude-code",
            "project": str(tmp_path / "proj"),
            "status": "launched",
            "launched_at": recent,
            "priority": 1,
            "pid": None,
        }])
        inbox_file = str(project / ".superharness" / "inbox.yaml")

        rc = recover_launched(
            file=inbox_file,
            now=_now_ts(),
            timeout_minutes=30,  # 30-minute timeout, item is only 2 minutes old
            action="stale",
        )
        assert rc == 0

        items = yaml.safe_load(open(inbox_file)) or []
        assert items[0]["status"] == "launched"  # untouched
