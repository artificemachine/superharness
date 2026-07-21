"""Iteration 3 of PLAN-coding-practices.md — commands/daemon_monitor.py is
the daemon's watcher-supervisor loop, extracted from a generated string
(daemon.py's old `_write_monitor_script`) into a real, importable, coverable
module. `run_monitor`'s side effects (spawn/sleep/liveness) are injectable so
the adopt -> wait -> respawn loop is testable without any real process.

Side-effect fence: no real watcher, monitor, or daemon process is started by
any test in this file. `run_monitor` loops forever by design; every test
terminates it deterministically by having a fake side effect raise a
sentinel exception once the assertion point is reached.
"""
from __future__ import annotations

import inspect
import json

import pytest

from superharness.commands import daemon_monitor


class _StopLoop(Exception):
    """Sentinel used to break out of run_monitor's infinite loop from a
    fake spawn/sleep/alive callable, once a test has seen what it needs."""


def _noop_sleep(seconds):
    pass


def test_monitor_uses_the_process_seam():
    source = inspect.getsource(daemon_monitor)
    assert "from superharness.engine.process import pid_alive" in source
    assert "GetExitCodeProcess" not in source
    assert "ctypes" not in source


def test_monitor_does_not_spawn_while_adopted_pid_is_alive(tmp_path):
    alive_calls = []

    def fake_alive(pid):
        alive_calls.append(pid)
        if len(alive_calls) >= 3:
            raise _StopLoop()
        return True  # adopted watcher stays alive

    def fake_spawn():
        raise AssertionError("must not spawn while the adopted pid is alive")

    with pytest.raises(_StopLoop):
        daemon_monitor.run_monitor(
            str(tmp_path), 30, "out.log", "err.log", watcher_pid=4242,
            spawn=fake_spawn, sleep=_noop_sleep, alive=fake_alive,
        )

    assert alive_calls == [4242, 4242, 4242]


def test_monitor_respawns_after_adopted_pid_dies(tmp_path):
    spawn_calls = []

    def fake_alive(pid):
        return False  # adopted watcher is already dead

    def fake_spawn():
        spawn_calls.append(1)
        raise _StopLoop()

    with pytest.raises(_StopLoop):
        daemon_monitor.run_monitor(
            str(tmp_path), 30, "out.log", "err.log", watcher_pid=4242,
            spawn=fake_spawn, sleep=_noop_sleep, alive=fake_alive,
        )

    assert spawn_calls == [1], "exactly one spawn must follow the adopted pid dying"


def test_monitor_writes_state_with_the_adopted_pid_first(tmp_path):
    (tmp_path / ".superharness").mkdir()

    def fake_alive(pid):
        raise _StopLoop()  # stop right after the pre-loop state write

    def fake_spawn():
        raise AssertionError("must not spawn before the first liveness check")

    with pytest.raises(_StopLoop):
        daemon_monitor.run_monitor(
            str(tmp_path), 30, "out.log", "err.log", watcher_pid=4242,
            spawn=fake_spawn, sleep=_noop_sleep, alive=fake_alive,
        )

    state = json.loads((tmp_path / ".superharness" / "daemon-state.json").read_text())
    assert state["watcher_pid"] == 4242, "the first state write must carry the adopted pid, not a freshly spawned one"


def test_monitor_state_file_shape_is_unchanged(tmp_path):
    (tmp_path / ".superharness").mkdir()

    def fake_alive(pid):
        raise _StopLoop()

    def fake_spawn():
        raise AssertionError("unreachable")

    with pytest.raises(_StopLoop):
        daemon_monitor.run_monitor(
            str(tmp_path), 30, "out.log", "err.log", watcher_pid=4242,
            spawn=fake_spawn, sleep=_noop_sleep, alive=fake_alive,
        )

    state = json.loads((tmp_path / ".superharness" / "daemon-state.json").read_text())
    assert set(state.keys()) == {"pid", "watcher_pid", "project", "interval", "log_out", "log_err"}


def test_monitor_respawns_when_adopted_pid_is_already_dead_on_start(tmp_path):
    """Chaos: stale adopted pid, dead from the very first check. Must
    respawn exactly once, not spin or crash."""
    spawn_calls = []

    def fake_alive(pid):
        return False

    def fake_spawn():
        spawn_calls.append(1)
        raise _StopLoop()

    with pytest.raises(_StopLoop):
        daemon_monitor.run_monitor(
            str(tmp_path), 30, "out.log", "err.log", watcher_pid=9999,
            spawn=fake_spawn, sleep=_noop_sleep, alive=fake_alive,
        )

    assert spawn_calls == [1]


def test_main_parses_argv_and_calls_run_monitor(monkeypatch, tmp_path):
    captured = {}

    def fake_run_monitor(project_dir, interval, out_log, err_log, watcher_pid, **kwargs):
        captured["args"] = (project_dir, interval, out_log, err_log, watcher_pid)

    monkeypatch.setattr(daemon_monitor, "run_monitor", fake_run_monitor)

    daemon_monitor.main([str(tmp_path), "30", "out.log", "err.log", "4242"])

    assert captured["args"] == (str(tmp_path), 30, "out.log", "err.log", 4242)


def test_main_with_no_args_exits_cleanly_instead_of_tracebacking():
    with pytest.raises(SystemExit) as exc_info:
        daemon_monitor.main([])
    assert exc_info.value.code == 2


def test_main_with_help_flag_exits_cleanly():
    with pytest.raises(SystemExit) as exc_info:
        daemon_monitor.main(["--help"])
    assert exc_info.value.code == 2
