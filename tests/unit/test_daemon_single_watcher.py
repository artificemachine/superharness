"""Iteration 4 — `shux daemon start` must spawn exactly one watcher, and
`shux daemon stop` must leave no orphan holding the lock.

Before this fix:
  - `_start_daemon` spawned a watcher directly (`_spawn_watcher()`), then
    handed its pid to the generated monitor script as `watcher_pid` — which
    parsed it (`watcher_pid = int(sys.argv[5])`) and never used it again,
    instead calling its own `spawn()` unconditionally on startup. Two
    watcher processes running per `daemon start`.
  - The second watcher is spawned with `start_new_session=True`, putting it
    in its own process group — so `_stop_daemon`'s `killpg` on the monitor's
    group never reaches it, leaving a permanent orphan.

Side-effect fence: no real daemon is spawned in these tests. `_stop_daemon`'s
process-signalling is asserted with `os.kill`/`_is_pid_alive` stubbed.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from superharness.commands import daemon as daemon_mod
from superharness.commands import daemon_monitor


# ---------------------------------------------------------------------------
# Monitor adopts the already-spawned watcher
#
# Rewritten in iteration 3 of PLAN-coding-practices.md: this class used to
# assert on the *text* of a generated script (`daemon_mod._write_monitor_script`).
# That function no longer exists — the monitor is now a real module,
# commands/daemon_monitor.py, exercised here behaviourally instead. Full
# coverage of its adopt/respawn loop lives in tests/unit/test_daemon_monitor.py;
# this class keeps the two properties this file's history cares about most
# (adopts rather than spawns, and launches as `-m`), plus a Windows-safety
# assertion inherited from `pid_alive` no longer being reimplemented here.
# ---------------------------------------------------------------------------

class _Stop(Exception):
    pass


class TestMonitorAdoptsWatcher:
    def test_monitor_adopts_passed_watcher_pid(self, tmp_path):
        (tmp_path / ".superharness").mkdir()
        seen_pids = []

        def fake_alive(pid):
            seen_pids.append(pid)
            raise _Stop()

        def fake_spawn():
            raise AssertionError(
                "the monitor spawned a fresh watcher instead of adopting "
                "the passed watcher_pid — this is the second-watcher bug"
            )

        with pytest.raises(_Stop):
            daemon_monitor.run_monitor(
                str(tmp_path), 30, str(tmp_path / "out.log"), str(tmp_path / "err.log"),
                watcher_pid=4242, spawn=fake_spawn, sleep=lambda s: None, alive=fake_alive,
            )

        assert seen_pids and seen_pids[0] == 4242, (
            "the monitor must check liveness of the adopted watcher_pid first"
        )

    def test_monitor_does_not_spawn_before_first_wait(self, tmp_path):
        (tmp_path / ".superharness").mkdir()
        spawned = []

        def fake_alive(pid):
            raise _Stop()  # stop as soon as the first liveness check happens

        def fake_spawn():
            spawned.append(1)
            raise _Stop()

        with pytest.raises(_Stop):
            daemon_monitor.run_monitor(
                str(tmp_path), 30, str(tmp_path / "out.log"), str(tmp_path / "err.log"),
                watcher_pid=4242, spawn=fake_spawn, sleep=lambda s: None, alive=fake_alive,
            )

        assert not spawned, (
            "spawn() must not be called before the adopted watcher's first "
            "liveness check — this is the second-watcher bug"
        )

    def test_start_launches_monitor_as_a_module(self, tmp_path, monkeypatch):
        """`_start_daemon`'s _monitor_argv must invoke the real module via
        `-m`, not a generated script path."""
        project_dir = tmp_path / "proj"
        (project_dir / ".superharness").mkdir(parents=True)

        captured = {}

        class FakeProc:
            pid = 555

        def fake_popen(cmd, *args, **kwargs):
            # The monitor is launched via subprocess.Popen on Windows (no
            # os.fork) and via os.execvpe on POSIX. Distinguish it from the
            # watcher spawn (also a Popen, also carrying `-m`) by module name,
            # so this assertion holds on every platform.
            if "superharness.commands.daemon_monitor" in cmd:
                captured["argv"] = cmd
                raise _Stop()
            return FakeProc()

        def fake_execvpe(path, argv, env):
            captured["argv"] = argv
            raise _Stop()

        monkeypatch.setattr(daemon_mod.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(daemon_mod, "_check_version_and_upgrade", lambda project_dir: None)
        if hasattr(daemon_mod.os, "fork"):
            monkeypatch.setattr(daemon_mod.os, "fork", lambda: 0)
            monkeypatch.setattr(daemon_mod.os, "setsid", lambda: None, raising=False)
            monkeypatch.setattr(daemon_mod.os, "chdir", lambda p: None)
            monkeypatch.setattr(daemon_mod.os, "umask", lambda m: None, raising=False)
            monkeypatch.setattr(daemon_mod.os, "closerange", lambda a, b: None, raising=False)
            monkeypatch.setattr(daemon_mod.os, "open", lambda *a, **k: 0)
            monkeypatch.setattr(daemon_mod.os, "execvpe", fake_execvpe)

        with pytest.raises(_Stop):
            daemon_mod._start_daemon(project_dir, 30)

        argv = captured["argv"]
        assert "-m" in argv
        assert "superharness.commands.daemon_monitor" in argv
        assert str(555) in argv, "the monitor argv must carry the spawned watcher's pid"


# ---------------------------------------------------------------------------
# _stop_daemon — must kill the watcher, not only the monitor
# ---------------------------------------------------------------------------

def _write_state(project_dir: Path, pid: int, watcher_pid: int | None) -> None:
    state = {"pid": pid, "project": str(project_dir), "interval": 30}
    if watcher_pid is not None:
        state["watcher_pid"] = watcher_pid
    daemon_mod._write_state(project_dir, state)


class TestStopKillsWatcher:
    """Iteration 4 of PLAN-coding-practices.md moved the killpg/getpgid
    escalation dance behind engine.process.terminate_group. These tests are
    rewritten to monkeypatch that seam directly — patching daemon_mod.os.killpg
    / .getpgid would no longer intercept anything, since daemon.py no longer
    calls them itself. Full escalation/polling correctness (SIGTERM then
    SIGKILL, Windows/no-pgid degradation, dead-pid idempotency) is covered
    by tests/unit/engine/test_process_seam.py::TestTerminateGroup; these
    tests cover only _stop_daemon's own orchestration.
    """

    def test_stop_kills_the_watcher_not_only_the_monitor(self, tmp_path, monkeypatch):
        (tmp_path / ".superharness").mkdir()
        _write_state(tmp_path, pid=100, watcher_pid=200)

        monkeypatch.setattr(daemon_mod, "_is_pid_alive", lambda pid: True)
        terminated = []
        monkeypatch.setattr(daemon_mod, "terminate_group", lambda pid, **kwargs: terminated.append(pid))

        daemon_mod._stop_daemon(tmp_path)

        assert 200 in terminated, (
            "the watcher pid must be terminated directly — a process-group "
            "signal to the monitor's group does not reach it (start_new_session=True)"
        )
        assert 100 in terminated

    def test_stop_does_not_terminate_an_already_dead_pid(self, tmp_path, monkeypatch):
        """Chaos: a stale watcher_pid belonging to a dead process must not
        raise and must not be signalled."""
        (tmp_path / ".superharness").mkdir()
        _write_state(tmp_path, pid=100, watcher_pid=200)

        def fake_alive(pid):
            return pid == 100  # only the monitor is alive; watcher is stale

        monkeypatch.setattr(daemon_mod, "_is_pid_alive", fake_alive)
        terminated = []
        monkeypatch.setattr(daemon_mod, "terminate_group", lambda pid, **kwargs: terminated.append(pid))

        daemon_mod._stop_daemon(tmp_path)  # must not raise

        assert terminated == [100], "must not attempt to terminate an already-dead watcher pid"

    def test_stop_removes_state_file_after_terminating(self, tmp_path, monkeypatch):
        (tmp_path / ".superharness").mkdir()
        _write_state(tmp_path, pid=100, watcher_pid=200)

        monkeypatch.setattr(daemon_mod, "_is_pid_alive", lambda pid: True)
        monkeypatch.setattr(daemon_mod, "terminate_group", lambda pid, **kwargs: None)

        state_file = daemon_mod._state_file(tmp_path)
        assert state_file.exists()

        daemon_mod._stop_daemon(tmp_path)

        assert not state_file.exists()

    def test_stop_passes_the_configured_escalation_budget(self, tmp_path, monkeypatch):
        (tmp_path / ".superharness").mkdir()
        _write_state(tmp_path, pid=100, watcher_pid=None)

        monkeypatch.setattr(daemon_mod, "_is_pid_alive", lambda pid: True)
        monkeypatch.setattr(daemon_mod, "_STOP_POLL_TIMEOUT_S", 2.5)
        monkeypatch.setattr(daemon_mod, "_STOP_POLL_INTERVAL_S", 0.05)
        calls = []

        def fake_terminate_group(pid, **kwargs):
            calls.append((pid, kwargs))

        monkeypatch.setattr(daemon_mod, "terminate_group", fake_terminate_group)

        daemon_mod._stop_daemon(tmp_path)

        assert calls == [(100, {"escalate_after": 2.5, "poll_interval": 0.05})]
