"""engine/process.py is the single seam for pid-liveness checks.

Iteration 1 of PLAN-coding-practices.md: establish `pid_alive` and correct
the Windows-mechanism comment introduced by `3eeda989`, which claimed
`os.kill(pid, 0)` calls `TerminateProcess` on Windows. It does not — CPython
special-cases signal 0 to `GenerateConsoleCtrlEvent`, matching the other four
comments already in this codebase (inbox_dispatch.py, operator.py,
inbox.py, mcp/cli.py).

Iteration 2: every duplicate pid-liveness implementation is migrated to call
`pid_alive`, with one deliberate, documented exception — `daemon.py`'s
`_write_monitor_script` still writes a standalone generated script containing
its own `pid_alive()` (already Windows-correct since `3eeda989`). That script
is not a real, directly-executed module today: it is a string literal daemon.py
writes to `.superharness/daemon-monitor.py` in the *target* project, run by
whatever interpreter `_find_superharness_python()` picks. Iteration 3 of
PLAN-coding-practices.md replaces this entire generated-string mechanism with
a real importable module (`commands/daemon_monitor.py`) invoked via `-m`,
which is where this last occurrence is retired. The ratchets below exclude
only that known, already-scheduled region of daemon.py — everywhere else,
including the rest of daemon.py's own real code, is held to zero.
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

from superharness.commands import daemon as daemon_mod
from superharness.engine.process import pid_alive

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _REPO_ROOT / "src" / "superharness"
_PROCESS_PY = _SRC_ROOT / "engine" / "process.py"
_DAEMON_PY = _SRC_ROOT / "commands" / "daemon.py"


def _daemon_source_excluding_generated_script() -> str:
    """daemon.py's real source, with the still-embedded generated monitor
    script (deferred to iteration 3, see module docstring above) cut out."""
    text = _DAEMON_PY.read_text()
    start = text.index("def _write_monitor_script")
    end = text.index("def _cleanup_monitor_script")
    return text[:start] + text[end:]


def _source_text_for_ratchet(path: Path) -> str:
    if path == _DAEMON_PY:
        return _daemon_source_excluding_generated_script()
    return path.read_text()


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
    """Iteration 2 ratchets — see module docstring for the one documented
    exception (daemon.py's still-embedded generated monitor script,
    deferred to iteration 3)."""

    def test_no_duplicate_ctypes_liveness_impls(self):
        hits = []
        for f in sorted(_SRC_ROOT.rglob("*.py")):
            if f == _PROCESS_PY:
                continue
            if "GetExitCodeProcess" in _source_text_for_ratchet(f):
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
            if pattern.search(_source_text_for_ratchet(f)):
                hits.append(str(f.relative_to(_REPO_ROOT)))
        assert not hits, (
            f"raw os.kill(pid, 0) liveness probe(s) found outside "
            f"engine/process.py: {hits}"
        )
