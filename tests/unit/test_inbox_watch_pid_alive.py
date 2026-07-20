"""Iteration 2 of PLAN-coding-practices.md — inbox_watch.py's two pid-liveness
sites (`_pid_is_running`, correct-but-duplicated; `_pid_alive`, broken with no
Windows branch) must both route through the process seam.
"""
from __future__ import annotations

import os

from superharness.commands import inbox_watch


def test_watcher_pid_alive_uses_the_seam(monkeypatch):
    calls = []

    def _recorder(pid):
        calls.append(pid)
        return True

    def _fail_if_called(pid, sig):
        raise AssertionError("inbox_watch._pid_alive must not call os.kill directly")

    monkeypatch.setattr("superharness.engine.process.pid_alive", _recorder)
    monkeypatch.setattr(os, "kill", _fail_if_called)

    assert inbox_watch._pid_alive(4242) is True
    assert calls == [4242]


def test_watcher_pid_is_running_uses_the_seam(monkeypatch):
    calls = []

    def _recorder(pid):
        calls.append(pid)
        return False

    def _fail_if_called(pid, sig):
        raise AssertionError("inbox_watch._pid_is_running must not call os.kill directly")

    monkeypatch.setattr("superharness.engine.process.pid_alive", _recorder)
    monkeypatch.setattr(os, "kill", _fail_if_called)

    assert inbox_watch._pid_is_running(4242) is False
    assert calls == [4242]


def test_watcher_pid_is_running_none_is_false():
    assert inbox_watch._pid_is_running(None) is False
