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
import signal
import subprocess
import sys
from pathlib import Path

from superharness.engine import process as process_mod
from superharness.engine.process import pid_alive, signal_process_group, terminate, terminate_group

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

    def test_no_raw_killpg_outside_the_seam(self):
        """No file other than engine/process.py may send a group signal
        directly. `os.getpgid` alone (without a matching `os.killpg`) is a
        separate, narrower case — see the next test."""
        hits = []
        for f in sorted(_SRC_ROOT.rglob("*.py")):
            if f == _PROCESS_PY:
                continue
            if "os.killpg" in f.read_text():
                hits.append(str(f.relative_to(_REPO_ROOT)))
        assert not hits, (
            f"raw os.killpg usage found outside engine/process.py: {hits}"
        )

    def test_getpgid_outside_the_seam_is_used_only_for_the_self_check(self):
        """`engine/operator.py` is a deliberate, narrow exception: it calls
        `os.getpgid` three times, but only to compare against `os.getpid()`
        before deciding whether to signal at all — never signalling its own
        process group, which a coincidental pgid match would otherwise
        SIGTERM/SIGKILL the operator itself. The actual signal-sending
        already goes through `engine.process.signal_process_group` (proven
        by the previous test finding zero `os.killpg` calls here). This is
        not the killpg/getpgid boilerplate duplication the seam exists to
        eliminate — it is a caller-specific safety check that doesn't belong
        in a general-purpose primitive used by callers with no reason to
        make the same comparison."""
        hits = []
        for f in sorted(_SRC_ROOT.rglob("*.py")):
            if f == _PROCESS_PY:
                continue
            if "os.getpgid" in f.read_text():
                hits.append(f.relative_to(_REPO_ROOT).as_posix())
        assert hits == ["src/superharness/engine/operator.py"], (
            f"os.getpgid usage outside engine/process.py changed shape: {hits}. "
            "If this is a new site, route it through signal_process_group instead "
            "of reimplementing the getpgid dance; if operator.py's own count changed, "
            "update this ratchet after confirming the new site is the same "
            "self-pgid safety check, not a duplicated signal-dispatch path."
        )


# ---------------------------------------------------------------------------
# Iteration 4 — terminate / signal_process_group / terminate_group
# ---------------------------------------------------------------------------

class TestTerminate:
    def test_terminate_is_idempotent_on_dead_pid(self, tmp_path, monkeypatch):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        # Must not raise, whether the OS reports ProcessLookupError or some
        # other OSError for an already-reaped pid.
        terminate(child.pid)

    def test_terminate_rejects_nonpositive(self):
        terminate(0)
        terminate(-1)

    def test_terminate_sends_sigterm_to_a_real_child(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            terminate(proc.pid)
            assert proc.wait(timeout=5) != 0 or True  # exited; exact code is platform-dependent
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)


class TestSignalProcessGroup:
    def test_signal_process_group_falls_back_to_single_pid_without_killpg(self, monkeypatch):
        monkeypatch.delattr(os, "killpg", raising=False)
        kills = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((pid, sig)))
        signal_process_group(4242, 15)
        assert kills == [(4242, 15)]

    def test_signal_process_group_uses_killpg_when_available(self, monkeypatch):
        killpg_calls = []
        monkeypatch.setattr(os, "getpgid", lambda pid: pid, raising=False)
        monkeypatch.setattr(os, "killpg", lambda pgid, sig: killpg_calls.append((pgid, sig)), raising=False)
        signal_process_group(4242, 15)
        assert killpg_calls == [(4242, 15)]

    def test_signal_process_group_degrades_on_getpgid_oserror(self, monkeypatch):
        def _raise(pid):
            raise OSError("no such process")

        monkeypatch.setattr(os, "getpgid", _raise, raising=False)
        monkeypatch.setattr(os, "killpg", lambda pgid, sig: (_ for _ in ()).throw(
            AssertionError("must not call killpg when getpgid failed")
        ), raising=False)
        kills = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((pid, sig)))
        signal_process_group(4242, 15)
        assert kills == [(4242, 15)]


class TestTerminateGroup:
    def test_terminate_group_falls_back_to_single_pid_without_killpg(self, monkeypatch):
        monkeypatch.delattr(os, "killpg", raising=False)
        kills = []
        monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((pid, sig)))
        monkeypatch.setattr(process_mod, "pid_alive", lambda pid: False)

        terminate_group(4242, escalate_after=None)

        assert kills == [(4242, signal.SIGTERM)]

    def test_terminate_group_sigterm_only_when_escalate_after_is_none(self, monkeypatch):
        """The shape needed inside a signal handler: one signal, no blocking."""
        sent = []
        monkeypatch.setattr(process_mod, "signal_process_group", lambda pid, sig: sent.append((pid, sig)))
        slept = []
        terminate_group(4242, escalate_after=None, sleep=lambda s: slept.append(s))
        assert sent == [(4242, signal.SIGTERM)]
        assert slept == []

    def test_terminate_group_escalates_after_timeout(self, monkeypatch):
        sent = []
        monkeypatch.setattr(process_mod, "signal_process_group", lambda pid, sig: sent.append((pid, sig)))
        terminated = []
        monkeypatch.setattr(process_mod, "terminate", lambda pid: terminated.append(pid))
        monkeypatch.setattr(process_mod, "pid_alive", lambda pid: True)  # never dies

        clock = {"t": 0.0}

        def fake_now():
            return clock["t"]

        def fake_sleep(seconds):
            clock["t"] += seconds

        terminate_group(4242, escalate_after=1.0, poll_interval=0.3, sleep=fake_sleep, now=fake_now)

        # SIGTERM to the group is the first move on every platform.
        assert sent[0] == (4242, signal.SIGTERM)
        if os.name == "nt":
            # Windows has no SIGKILL / process groups: escalation is a
            # forcible TerminateProcess via terminate().
            assert terminated == [4242], "Windows escalation must go through terminate()"
        else:
            assert sent[-1] == (4242, signal.SIGKILL)
            assert sent.count((4242, signal.SIGKILL)) == 1, "SIGKILL must be sent exactly once"

    def test_terminate_group_does_not_escalate_if_pid_dies_in_time(self, monkeypatch):
        sent = []
        monkeypatch.setattr(process_mod, "signal_process_group", lambda pid, sig: sent.append((pid, sig)))

        alive_calls = {"n": 0}

        def fake_alive(pid):
            alive_calls["n"] += 1
            return alive_calls["n"] < 2  # dies on the second check

        monkeypatch.setattr(process_mod, "pid_alive", fake_alive)

        clock = {"t": 0.0}
        terminate_group(
            4242, escalate_after=5.0, poll_interval=0.1,
            sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
            now=lambda: clock["t"],
        )

        assert sent == [(4242, signal.SIGTERM)], "must not escalate to SIGKILL once the pid is confirmed dead"

    def test_terminate_group_rejects_nonpositive(self, monkeypatch):
        sent = []
        monkeypatch.setattr(process_mod, "signal_process_group", lambda pid, sig: sent.append((pid, sig)))
        terminate_group(0)
        terminate_group(-1)
        assert sent == []
