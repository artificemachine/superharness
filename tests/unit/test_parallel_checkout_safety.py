"""
Concurrency-focused regression tests for parallel checkout safety.
RED phase: tests fail until GREEN implementation is in place.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

# These imports will fail (RED) until inbox.py has claim() and _deps_satisfied()
from superharness.engine.inbox import (
    _deps_satisfied,
    claim,
    enqueue,
    launch,
    next_pending,
    recover_launched,
    _load_items,
)
from superharness.commands.inbox_dispatch import _MkdirLock

INBOX_HEADER = (
    "# Delegation inbox\n"
    "# status: pending|launched|running|done|failed|stale\n"
)
NOW = "2026-01-01T00:00:00Z"
NOW2 = "2026-01-01T00:00:01Z"
PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_inbox(tmp_path: Path, items: list[dict]) -> str:
    """Create inbox.yaml with given items."""
    f = tmp_path / "inbox.yaml"
    f.write_text(INBOX_HEADER + yaml.dump(items, default_flow_style=False))
    return str(f)


def _make_contract(tmp_path: Path, tasks: list[dict]) -> str:
    """Create contract.yaml with given tasks."""
    f = tmp_path / "contract.yaml"
    f.write_text(yaml.dump({"id": "test", "tasks": tasks}, default_flow_style=False))
    return str(f)


def _read_inbox_items(path: str) -> list[dict]:
    """Read current inbox items."""
    return _load_items(path)


# ---------------------------------------------------------------------------
# TestDepsSatisfied
# ---------------------------------------------------------------------------

class TestDepsSatisfied:
    def test_no_contract_file_returns_true(self, tmp_path):
        missing = str(tmp_path / "nope.yaml")
        assert _deps_satisfied(missing, "task-1") is True

    def test_task_not_in_contract_returns_true(self, tmp_path):
        contract = _make_contract(tmp_path, [
            {"id": "task-1", "status": "done", "blocked_by": None},
        ])
        assert _deps_satisfied(contract, "task-999") is True

    def test_blocked_by_none_returns_true(self, tmp_path):
        contract = _make_contract(tmp_path, [
            {"id": "task-1", "status": "todo", "blocked_by": None},
        ])
        assert _deps_satisfied(contract, "task-1") is True

    def test_blocked_by_done_returns_true(self, tmp_path):
        contract = _make_contract(tmp_path, [
            {"id": "dep-1", "status": "done"},
            {"id": "task-1", "status": "todo", "blocked_by": "dep-1"},
        ])
        assert _deps_satisfied(contract, "task-1") is True

    def test_blocked_by_not_done_returns_false(self, tmp_path):
        contract = _make_contract(tmp_path, [
            {"id": "dep-1", "status": "in_progress"},
            {"id": "task-1", "status": "todo", "blocked_by": "dep-1"},
        ])
        assert _deps_satisfied(contract, "task-1") is False

    def test_blocked_by_list_all_done_returns_true(self, tmp_path):
        contract = _make_contract(tmp_path, [
            {"id": "dep-1", "status": "done"},
            {"id": "dep-2", "status": "done"},
            {"id": "task-1", "status": "todo", "blocked_by": ["dep-1", "dep-2"]},
        ])
        assert _deps_satisfied(contract, "task-1") is True

    def test_blocked_by_list_one_not_done_returns_false(self, tmp_path):
        contract = _make_contract(tmp_path, [
            {"id": "dep-1", "status": "done"},
            {"id": "dep-2", "status": "in_progress"},
            {"id": "task-1", "status": "todo", "blocked_by": ["dep-1", "dep-2"]},
        ])
        assert _deps_satisfied(contract, "task-1") is False


# ---------------------------------------------------------------------------
# TestClaimAtomic
# ---------------------------------------------------------------------------

class TestClaimAtomic:
    def test_claim_transitions_to_launched(self, tmp_path):
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        rc = claim(inbox, NOW)
        assert rc == 0
        items = _read_inbox_items(inbox)
        assert items[0]["status"] == "launched"
        assert items[0]["retry_count"] == 1

    def test_claim_prints_json(self, tmp_path):
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            claim(inbox, NOW)
        output = buf.getvalue().strip()
        assert output, "claim() should print JSON"
        data = json.loads(output)
        assert data["id"] == "i1"
        assert data["task"] == "t1"
        assert data["to"] == "claude-code"
        assert data["project"] == "/p"
        assert data["retry_count"] == 1
        assert data["max_retries"] == 3
        assert "priority" in data

    def test_claim_empty_inbox_returns_nothing(self, tmp_path):
        inbox = _make_inbox(tmp_path, [])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = claim(inbox, NOW)
        assert rc == 0
        assert buf.getvalue().strip() == ""

    def test_claim_skips_non_pending(self, tmp_path):
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "launched", "priority": 2, "retry_count": 1, "max_retries": 3},
            {"id": "i2", "to": "claude-code", "task": "t2", "project": "/p",
             "status": "done", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = claim(inbox, NOW)
        assert rc == 0
        assert buf.getvalue().strip() == ""

    def test_claim_exhausted_retries_marks_failed(self, tmp_path):
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 3, "max_retries": 3},
        ])
        rc = claim(inbox, NOW)
        assert rc == 4
        items = _read_inbox_items(inbox)
        assert items[0]["status"] == "failed"

    def test_claim_filters_by_target(self, tmp_path):
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
            {"id": "i2", "to": "codex-cli", "task": "t2", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = claim(inbox, NOW, target="codex-cli")
        assert rc == 0
        data = json.loads(buf.getvalue().strip())
        assert data["id"] == "i2"
        items = _read_inbox_items(inbox)
        assert items[0]["status"] == "pending"   # claude-code item untouched
        assert items[1]["status"] == "launched"  # codex-cli item claimed

    def test_claim_with_blocked_dep_skips(self, tmp_path):
        contract = _make_contract(tmp_path, [
            {"id": "dep-1", "status": "in_progress"},
            {"id": "t1", "status": "todo", "blocked_by": "dep-1"},
        ])
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = claim(inbox, NOW, contract_file=contract)
        assert rc == 0
        assert buf.getvalue().strip() == ""
        items = _read_inbox_items(inbox)
        assert items[0]["status"] == "pending"  # not claimed


# ---------------------------------------------------------------------------
# TestConcurrentClaim
# ---------------------------------------------------------------------------

class TestConcurrentClaim:
    def test_double_claim_prevented(self, tmp_path):
        """Two concurrent threads: only ONE item gets claimed."""
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])

        results = []
        outputs = []
        barrier = threading.Barrier(2)

        def _worker():
            barrier.wait()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = claim(inbox, NOW)
            results.append(rc)
            outputs.append(buf.getvalue().strip())

        t1 = threading.Thread(target=_worker)
        t2 = threading.Thread(target=_worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one thread should have claimed
        claimed_outputs = [o for o in outputs if o]
        assert len(claimed_outputs) == 1, f"Expected 1 claim, got: {outputs}"

        items = _read_inbox_items(inbox)
        assert items[0]["status"] == "launched"
        assert items[0]["retry_count"] == 1

    def test_parallel_agents_claim_different_items(self, tmp_path):
        """Two threads with different targets claim different items (no overlap).

        Uses inbox state (not stdout) to verify correctness, since
        contextlib.redirect_stdout patches sys.stdout globally and is not
        thread-safe when claim() holds the flock across a print() call.
        """
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
            {"id": "i2", "to": "codex-cli", "task": "t2", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])

        return_codes = {}
        barrier = threading.Barrier(2)

        def _worker(target):
            barrier.wait()
            # Suppress stdout: we verify via inbox state, not print output,
            # because redirect_stdout is not thread-safe.
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = claim(inbox, NOW, target=target)
            return_codes[target] = rc

        t1 = threading.Thread(target=_worker, args=("claude-code",))
        t2 = threading.Thread(target=_worker, args=("codex-cli",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both threads should have returned rc=0
        assert return_codes.get("claude-code") == 0
        assert return_codes.get("codex-cli") == 0

        # Both items should now be launched (each target claimed its own item)
        items = _read_inbox_items(inbox)
        status_map = {item["id"]: item["status"] for item in items}
        assert status_map["i1"] == "launched", f"i1 should be launched, got: {status_map}"
        assert status_map["i2"] == "launched", f"i2 should be launched, got: {status_map}"


# ---------------------------------------------------------------------------
# TestDependencyAwareScheduling
# ---------------------------------------------------------------------------

class TestDependencyAwareScheduling:
    def test_next_pending_skips_blocked_task(self, tmp_path):
        contract = _make_contract(tmp_path, [
            {"id": "dep-1", "status": "in_progress"},
            {"id": "t1", "status": "todo", "blocked_by": "dep-1"},
        ])
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = next_pending(inbox, contract_file=contract)
        assert rc == 0
        assert buf.getvalue().strip() == ""

    def test_next_pending_no_contract_unchanged(self, tmp_path):
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = next_pending(inbox)
        assert rc == 0
        data = json.loads(buf.getvalue().strip())
        assert data["id"] == "i1"

    def test_claim_skips_blocked_picks_eligible(self, tmp_path):
        contract = _make_contract(tmp_path, [
            {"id": "dep-1", "status": "in_progress"},
            {"id": "t1", "status": "todo", "blocked_by": "dep-1"},
            {"id": "t2", "status": "todo"},
        ])
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
            {"id": "i2", "to": "claude-code", "task": "t2", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = claim(inbox, NOW, contract_file=contract)
        assert rc == 0
        data = json.loads(buf.getvalue().strip())
        assert data["id"] == "i2"  # i1 is blocked, i2 is eligible
        items = _read_inbox_items(inbox)
        id_to_status = {item["id"]: item["status"] for item in items}
        assert id_to_status["i1"] == "pending"   # still blocked
        assert id_to_status["i2"] == "launched"  # claimed

    def test_claim_all_blocked_returns_nothing(self, tmp_path):
        contract = _make_contract(tmp_path, [
            {"id": "dep-1", "status": "in_progress"},
            {"id": "t1", "status": "todo", "blocked_by": "dep-1"},
        ])
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = claim(inbox, NOW, contract_file=contract)
        assert rc == 0
        assert buf.getvalue().strip() == ""

    def test_claim_after_dep_done_succeeds(self, tmp_path):
        contract = _make_contract(tmp_path, [
            {"id": "dep-1", "status": "done"},
            {"id": "t1", "status": "todo", "blocked_by": "dep-1"},
        ])
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = claim(inbox, NOW, contract_file=contract)
        assert rc == 0
        data = json.loads(buf.getvalue().strip())
        assert data["id"] == "i1"


# ---------------------------------------------------------------------------
# TestStaleLockRecovery
# ---------------------------------------------------------------------------

class TestStaleLockRecovery:
    def test_stale_dispatch_lock_dead_pid_auto_recovered(self, tmp_path):
        lock_dir = str(tmp_path / "inbox.yaml.lock.d")
        lock = _MkdirLock(lock_dir, stale_seconds=300)

        # Create the lock directory manually with a dead PID
        os.mkdir(lock_dir)
        pid_file = os.path.join(lock_dir, "owner.pid")
        with open(pid_file, "w") as f:
            f.write("99999999\n")  # non-existent PID

        # A new acquire() should auto-break the orphaned lock
        acquired = lock.acquire()
        assert acquired is True, "Should auto-break dead-PID lock and acquire"
        lock.release()

    def test_stale_dispatch_lock_age_auto_recovered(self, tmp_path):
        lock_dir = str(tmp_path / "inbox.yaml.lock.d")
        lock = _MkdirLock(lock_dir, stale_seconds=10)

        # Create lock dir with no PID, backdate mtime
        os.mkdir(lock_dir)
        stale_time = time.time() - 60  # 60s old, stale_seconds=10
        os.utime(lock_dir, (stale_time, stale_time))

        acquired = lock.acquire()
        assert acquired is True, "Should auto-break stale no-PID lock and acquire"
        lock.release()

    def test_fresh_lock_held_by_alive_pid_respected(self, tmp_path):
        lock_dir = str(tmp_path / "inbox.yaml.lock.d")

        # First, acquire via our process
        lock1 = _MkdirLock(lock_dir, stale_seconds=300)
        assert lock1.acquire() is True

        # Second acquire (different instance, same path) should fail
        lock2 = _MkdirLock(lock_dir, stale_seconds=300)
        acquired = lock2.acquire()
        assert acquired is False, "Should NOT break a lock held by our own alive PID"

        lock1.release()

    def test_recover_launched_retries_timed_out_item(self, tmp_path):
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "launched", "priority": 2, "retry_count": 1, "max_retries": 3,
             "launched_at": "2026-01-01T00:00:00Z"},
        ])
        # NOW2 is 1 second later, but timeout is 0 minutes → immediate expiry
        # Use action=retry and a very short timeout
        rc = recover_launched(inbox, "2026-01-01T01:00:00Z", timeout_minutes=0, action="retry")
        assert rc == 0
        items = _read_inbox_items(inbox)
        assert items[0]["status"] == "pending"

    def test_recover_launched_fails_exhausted_item(self, tmp_path):
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "launched", "priority": 2, "retry_count": 3, "max_retries": 3,
             "launched_at": "2026-01-01T00:00:00Z"},
        ])
        rc = recover_launched(inbox, "2026-01-01T01:00:00Z", timeout_minutes=0, action="retry")
        assert rc == 0
        items = _read_inbox_items(inbox)
        assert items[0]["status"] == "failed"

    def test_live_pid_not_recovered(self, tmp_path):
        our_pid = os.getpid()
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "launched", "priority": 2, "retry_count": 0, "max_retries": 3,
             "launched_at": "2026-01-01T00:00:00Z", "pid": our_pid},
        ])
        rc = recover_launched(inbox, "2026-01-01T01:00:00Z", timeout_minutes=0, action="retry")
        assert rc == 0
        items = _read_inbox_items(inbox)
        # Our PID is alive → item NOT recovered
        assert items[0]["status"] == "launched"


# ---------------------------------------------------------------------------
# TestSingleAgentUnchanged
# ---------------------------------------------------------------------------

class TestSingleAgentUnchanged:
    def test_next_pending_backward_compat(self, tmp_path):
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = next_pending(inbox)
        assert rc == 0
        data = json.loads(buf.getvalue().strip())
        assert data["id"] == "i1"

    def test_launch_cas_still_works(self, tmp_path):
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        rc = launch(inbox, "i1", NOW)
        assert rc == 0
        items = _read_inbox_items(inbox)
        assert items[0]["status"] == "launched"

    def test_launch_status_mismatch_returns_3(self, tmp_path):
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "launched", "priority": 2, "retry_count": 1, "max_retries": 3},
        ])
        rc = launch(inbox, "i1", NOW)
        assert rc == 3

    def test_enqueue_duplicate_rejected(self, tmp_path):
        inbox = _make_inbox(tmp_path, [
            {"id": "i1", "to": "claude-code", "task": "t1", "project": "/p",
             "status": "pending", "priority": 2, "retry_count": 0, "max_retries": 3},
        ])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = enqueue(inbox, "i2", "claude-code", "t1", "/p", 2, NOW)
        assert rc == 2
        assert "duplicate" in buf.getvalue()
