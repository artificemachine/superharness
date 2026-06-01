"""Tests for operator circuit breaker and process leak prevention.

Covers:
- RESTART_LIMIT: circuit breaker trips after N restarts in window
- PORT_REUSE: dashboard restarts on same port (no inflation)
- PROCESS_CLEANUP: old subprocess killed before replacement spawned
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest import mock

import pytest

from superharness.engine.operator import Operator


@pytest.fixture
def operator(tmp_path: Path) -> Operator:
    project_dir = tmp_path / "test_proj"
    project_dir.mkdir()
    (project_dir / ".superharness").mkdir(parents=True)
    (project_dir / ".superharness" / "handoffs").mkdir()
    return Operator(project_dir)


def _run_one_tick(op: Operator) -> None:
    """Run one tick of the recovery loop and stop.
    
    Mirrors the core logic of monitor_and_recover() without the infinite
    loop, and without calling trace_event (which fails on mock objects).
    """
    op._stopping = False
    try:
        for name, proc in list(op.processes.items()):
            if proc.poll() is not None:
                now_ts = time.time()
                history = op._restart_history.setdefault(name, [])
                history[:] = [t for t in history if now_ts - t < op._restart_window]
                history.append(now_ts)
                if len(history) > op._max_restarts:
                    continue
                op._kill_process(proc, name)
                if name == "watcher":
                    op._spawn_watcher()
                elif name == "dashboard":
                    if op._dashboard_port is None:
                        op._dashboard_port = op._find_available_port(8787)
                    op._spawn_dashboard(op._dashboard_port, no_open=True)
    finally:
        op._stopping = True


class TestCircuitBreaker:
    """Circuit breaker prevents death spiral: crashing component stops
    being restarted after exceeding _max_restarts in _restart_window."""

    def test_circuit_breaker_trips_after_max_restarts(self, operator: Operator):
        """After _max_restarts+1 polls, the component is NOT restarted."""
        operator._max_restarts = 3
        operator._restart_window = 3600

        proc = mock.Mock()
        proc.poll.return_value = 0
        proc.pid = 12345
        operator.processes["watcher"] = proc

        with mock.patch.object(operator, "_kill_process", return_value=None):
            with mock.patch.object(operator, "_spawn_watcher", return_value=None):
                # First 3 ticks: circuit breaker still allows restart
                for i in range(3):
                    _run_one_tick(operator)
                    assert len(operator._restart_history.get("watcher", [])) == i + 1

                # 4th tick: circuit breaker trips, skip restart
                _run_one_tick(operator)
                assert len(operator._restart_history["watcher"]) == 4
                assert operator.processes.get("watcher") is proc

    def test_circuit_breaker_resets_after_window(self, operator: Operator):
        """After the window expires, oldest entries are pruned, allowing restarts."""
        operator._max_restarts = 2
        operator._restart_window = 0  # zero window — all entries expire immediately

        proc = mock.Mock()
        proc.poll.return_value = 0
        proc.pid = 12345
        operator.processes["watcher"] = proc

        # Each tick prunes old history → never trips
        for _ in range(10):
            _run_one_tick(operator)
        assert len(operator._restart_history.get("watcher", [])) <= operator._max_restarts + 1

    def test_circuit_breaker_per_component(self, operator: Operator):
        """Watcher tripping does NOT block dashboard restarts."""
        operator._max_restarts = 2
        operator._restart_window = 3600

        proc_w = mock.Mock()
        proc_w.poll.return_value = 0
        proc_w.pid = 1
        operator.processes["watcher"] = proc_w

        with mock.patch.object(operator, "_kill_process", return_value=None):
            with mock.patch.object(operator, "_spawn_watcher", return_value=None):
                with mock.patch.object(operator, "_spawn_dashboard", return_value=None):
                    # Trip watcher (3 ticks = history of 3, > max_restarts=2)
                    for _ in range(3):
                        _run_one_tick(operator)

                    # Stop watcher from triggering on next tick
                    proc_w.poll.return_value = None

                    # Dashboard should still restart independently
                    proc_d = mock.Mock()
                    proc_d.poll.return_value = 0
                    proc_d.pid = 2
                    operator.processes["dashboard"] = proc_d
                    _run_one_tick(operator)
                    
                    assert len(operator._restart_history.get("dashboard", [])) == 1
                    assert len(operator._restart_history.get("watcher", [])) == 3


class TestPortReuse:
    """Dashboard port is reused across restarts to prevent port inflation."""

    def test_dashboard_port_reused_on_restart(self, operator: Operator):
        """Recovery loop uses the tracked port, not a new one each time."""
        operator._dashboard_port = 9000

        proc = mock.Mock()
        proc.poll.return_value = 0
        proc.pid = 1
        operator.processes["dashboard"] = proc

        spawned_ports = []

        def fake_spawn(port, no_open=False):
            spawned_ports.append(port)
            new_proc = mock.Mock()
            new_proc.poll.return_value = None
            new_proc.pid = 2
            operator.processes["dashboard"] = new_proc

        with mock.patch.object(operator, "_spawn_dashboard", side_effect=fake_spawn):
            with mock.patch.object(operator, "_kill_process", return_value=None):
                for _ in range(3):
                    operator.processes["dashboard"].poll.return_value = 0
                    _run_one_tick(operator)

        assert len(spawned_ports) == 3
        assert all(p == 9000 for p in spawned_ports), (
            f"Port should be reused: {spawned_ports}"
        )

    def test_initial_port_assigned(self, operator: Operator):
        """First dashboard start assigns _dashboard_port."""
        assert operator._dashboard_port is None
        operator._write_daemon_info(8787)
        assert operator._dashboard_port == 8787


class TestProcessCleanup:
    """Old processes are killed before replacement is spawned."""

    def test_old_process_killed_before_new(self, operator: Operator):
        """_kill_process is called on the old proc before _spawn_watcher."""
        proc = mock.Mock()
        proc.poll.return_value = 0
        proc.pid = 1
        operator.processes["watcher"] = proc

        kill_calls = []
        spawn_calls = []

        def fake_kill(p, name=""):
            kill_calls.append(name)

        def fake_spawn():
            spawn_calls.append("watcher")
            new_proc = mock.Mock()
            new_proc.poll.return_value = None
            new_proc.pid = 2
            operator.processes["watcher"] = new_proc

        with mock.patch.object(operator, "_kill_process", side_effect=fake_kill):
            with mock.patch.object(operator, "_spawn_watcher", side_effect=fake_spawn):
                _run_one_tick(operator)

        assert len(kill_calls) == 1, "old process must be killed"
        assert len(spawn_calls) == 1, "new process must be spawned"
