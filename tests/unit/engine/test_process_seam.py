"""engine/process.py is the single seam for pid-liveness checks.

Iteration 1 of PLAN-coding-practices.md: establish `pid_alive` and correct
the Windows-mechanism comment introduced by `3eeda989`, which claimed
`os.kill(pid, 0)` calls `TerminateProcess` on Windows. It does not — CPython
special-cases signal 0 to `GenerateConsoleCtrlEvent`, matching the other four
comments already in this codebase (inbox_dispatch.py, operator.py,
inbox.py, mcp/cli.py).
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys

from superharness.commands import daemon as daemon_mod
from superharness.engine.process import pid_alive


def test_pid_alive_true_for_current_process():
    assert pid_alive(os.getpid()) is True


def test_pid_alive_false_for_reaped_child():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert pid_alive(child.pid) is False


def test_pid_alive_rejects_nonpositive():
    assert pid_alive(0) is False
    assert pid_alive(-1) is False


def test_pid_alive_never_uses_os_kill_on_windows():
    source = inspect.getsource(pid_alive)
    nt_idx = source.find('os.name == "nt"')
    kill_idx = source.find("os.kill(")
    assert nt_idx != -1, "pid_alive has no os.name == \"nt\" branch"
    assert kill_idx != -1, "pid_alive has no os.kill( call"
    assert nt_idx < kill_idx, "the nt branch must appear before any os.kill( probe"


def test_daemon_monitor_comment_states_the_real_mechanism(tmp_path):
    (tmp_path / ".superharness").mkdir()
    script = daemon_mod._write_monitor_script(
        tmp_path, 30, tmp_path / "out.log", tmp_path / "err.log", watcher_pid=4242,
    )
    text = script.read_text()

    assert "TerminateProcess, not a probe" not in text
    assert "GenerateConsoleCtrlEvent" in text
