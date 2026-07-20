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

        def fake_spawn_watcher_popen(*args, **kwargs):
            return FakeProc()

        def fake_execvpe(path, argv, env):
            captured["argv"] = argv
            raise _Stop()

        monkeypatch.setattr(daemon_mod.subprocess, "Popen", fake_spawn_watcher_popen)
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
    def test_stop_kills_the_watcher_not_only_the_monitor(self, tmp_path, monkeypatch):
        (tmp_path / ".superharness").mkdir()
        _write_state(tmp_path, pid=100, watcher_pid=200)

        monkeypatch.setattr(daemon_mod, "_is_pid_alive", lambda pid: True)
        # raising=False: Windows os has neither killpg nor getpgid — the
        # production code hasattr-guards them, the test must not require them.
        monkeypatch.setattr(daemon_mod.os, "killpg", lambda pgid, sig: None, raising=False)
        monkeypatch.setattr(daemon_mod.os, "getpgid", lambda pid: pid, raising=False)
        killed = []
        monkeypatch.setattr(daemon_mod.os, "kill", lambda pid, sig: killed.append(pid))
        monkeypatch.setattr(daemon_mod, "_STOP_POLL_TIMEOUT_S", 0.05)
        monkeypatch.setattr(daemon_mod, "_STOP_POLL_INTERVAL_S", 0.01)

        daemon_mod._stop_daemon(tmp_path)

        assert 200 in killed, "the watcher pid must be signalled directly — killpg on the monitor's group does not reach it (start_new_session=True)"

    def test_stop_removes_state_only_after_processes_are_gone(self, tmp_path, monkeypatch):
        """Also covers the chaos case: a stale watcher_pid belonging to a
        dead process must not raise and must not block cleanup forever."""
        (tmp_path / ".superharness").mkdir()
        _write_state(tmp_path, pid=100, watcher_pid=200)

        alive_calls = {"monitor": 0, "watcher": 0}

        def fake_alive(pid):
            if pid == 100:
                alive_calls["monitor"] += 1
                return alive_calls["monitor"] <= 2  # dies after 2 checks
            if pid == 200:
                alive_calls["watcher"] += 1
                return False  # stale/dead from the start
            return False

        monkeypatch.setattr(daemon_mod, "_is_pid_alive", fake_alive)
        monkeypatch.setattr(daemon_mod.os, "killpg", lambda pgid, sig: None, raising=False)
        monkeypatch.setattr(daemon_mod.os, "getpgid", lambda pid: pid, raising=False)
        monkeypatch.setattr(daemon_mod.os, "kill", lambda pid, sig: None)
        monkeypatch.setattr(daemon_mod, "_STOP_POLL_TIMEOUT_S", 1.0)
        monkeypatch.setattr(daemon_mod, "_STOP_POLL_INTERVAL_S", 0.01)

        state_file = daemon_mod._state_file(tmp_path)
        assert state_file.exists()

        daemon_mod._stop_daemon(tmp_path)  # must not raise

        assert not state_file.exists(), "state file must be removed once both pids are confirmed dead"
        assert alive_calls["monitor"] >= 2, "must have polled until the monitor pid actually died"
