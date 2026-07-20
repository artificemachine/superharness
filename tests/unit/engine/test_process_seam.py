"""engine/process.py is the single seam for pid-liveness checks.

Iteration 1 of PLAN-coding-practices.md: establish `pid_alive` and correct
the Windows-mechanism comment introduced by `3eeda989`, which claimed
`os.kill(pid, 0)` calls `TerminateProcess` on Windows. It does not — CPython
special-cases signal 0 to `GenerateConsoleCtrlEvent`, matching the other four
comments already in this codebase (inbox_dispatch.py, operator.py,
inbox.py, mcp/cli.py).

Iteration 2: every duplicate pid-liveness implementation is migrated to call
`pid_alive`, with one deliberate, documented exception at the time — daemon.py's
`_write_monitor_script` still wrote a standalone generated script containing
its own `pid_alive()`. Iteration 3 deleted that generated-string mechanism
entirely (see `commands/daemon_monitor.py`, now a real importable module
invoked via `-m`), which retired the last occurrence. The ratchets below now
hold every file under `src/` to zero, with no exception.
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

from superharness.engine.process import pid_alive

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _REPO_ROOT / "src" / "superharness"
_PROCESS_PY = _SRC_ROOT / "engine" / "process.py"
_DAEMON_PY = _SRC_ROOT / "commands" / "daemon.py"


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


def test_no_generated_monitor_script_remains():
    """Iteration 3 superseded this test — it used to write the generated
    monitor script (`daemon_mod._write_monitor_script`) and assert on its
    text. That function is gone; the monitor is now a real module
    (commands/daemon_monitor.py, see test_daemon_monitor.py for its
    behavioural coverage). This guards the deletion from silently coming
    back."""
    from superharness.commands import daemon as daemon_mod
    assert not hasattr(daemon_mod, "_write_monitor_script")
    assert not hasattr(daemon_mod, "_cleanup_monitor_script")
    assert "TerminateProcess, not a probe" not in _DAEMON_PY.read_text()


def test_pid_alive_treats_permission_error_as_alive(monkeypatch):
    """Chaos: a pid owned by another user raises PermissionError from
    os.kill, which means the process exists — pid_alive must not report it
    as dead."""
    def _raise_permission_error(pid, sig):
        raise PermissionError("owned by another user")

    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(os, "kill", _raise_permission_error)
    assert pid_alive(4242) is True


class TestNoDuplicateLivenessImplementations:
    """Ratchets, held to zero with no exception as of iteration 3."""

    def test_no_duplicate_ctypes_liveness_impls(self):
        hits = []
        for f in sorted(_SRC_ROOT.rglob("*.py")):
            if f == _PROCESS_PY:
                continue
            if "GetExitCodeProcess" in f.read_text():
                hits.append(str(f.relative_to(_REPO_ROOT)))
        assert not hits, (
            f"duplicate ctypes liveness implementation(s) found outside "
            f"engine/process.py: {hits}"
        )

    def test_no_raw_os_kill_zero_probe(self):
        import re
        pattern = re.compile(r"os\.kill\([^)]*,\s*0\)")
        hits = []
        for f in sorted(_SRC_ROOT.rglob("*.py")):
            if f == _PROCESS_PY:
                continue
            if pattern.search(f.read_text()):
                hits.append(str(f.relative_to(_REPO_ROOT)))
        assert not hits, (
            f"raw os.kill(pid, 0) liveness probe(s) found outside "
            f"engine/process.py: {hits}"
        )
