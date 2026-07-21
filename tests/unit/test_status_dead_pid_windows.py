"""Iteration 2 of PLAN-coding-practices.md — status.py's dead-pid check must
route through the process seam rather than a raw os.kill(pid, 0) probe,
which is not a liveness check on Windows.
"""
from __future__ import annotations

import os

from superharness.commands import status as status_mod


def _fake_state_reader(monkeypatch, inbox_items, tasks=None):
    monkeypatch.setattr(
        "superharness.engine.state_reader.get_inbox_items",
        lambda project_dir: inbox_items,
    )
    monkeypatch.setattr(
        "superharness.engine.state_reader.get_tasks",
        lambda project_dir: tasks or [],
    )


def test_status_dead_pid_check_uses_the_seam(tmp_path, monkeypatch):
    calls = []

    def _recorder(pid):
        calls.append(pid)
        return False  # pretend dead

    def _fail_if_called(pid, sig):
        raise AssertionError("status.py must not call os.kill directly for liveness")

    _fake_state_reader(monkeypatch, [
        {"id": "i1", "task": "t1", "status": "launched",
         "launched_at": "2026-01-01T00:00:00Z", "pid": 4242},
    ])
    monkeypatch.setattr(status_mod, "pid_alive", _recorder)
    monkeypatch.setattr(os, "kill", _fail_if_called)

    result = status_mod._deep_inbox_health(str(tmp_path))

    assert calls == [4242]
    assert any(d["pid"] == 4242 for d in result["dead_pid"])


def test_status_dead_pid_check_preserves_valueerror_handling(tmp_path, monkeypatch):
    """A non-numeric pid must still be treated as dead (int(pid) raising
    ValueError), independent of the liveness seam."""
    _fake_state_reader(monkeypatch, [
        {"id": "i1", "task": "t1", "status": "launched",
         "launched_at": "2026-01-01T00:00:00Z", "pid": "not-a-pid"},
    ])
    monkeypatch.setattr(status_mod, "pid_alive", lambda pid: True)

    result = status_mod._deep_inbox_health(str(tmp_path))

    assert any(d["pid"] == "not-a-pid" for d in result["dead_pid"])
