"""Watcher respawn throttling in Operator.monitor_and_recover.

The inbox watcher is intentionally one-shot: it runs a single cycle and
exits 0, and the operator's monitor loop respawns it. Before the fix, the
respawn happened on every monitor poll (5s), tripling the intended 15s
cadence and paying a full Python interpreter + superharness import chain
every poll. These tests pin the throttled behavior: a clean watcher exit
is only respawned once the configured watcher interval has elapsed since
the previous spawn.
"""
from __future__ import annotations

import threading
import time

import pytest

from superharness.engine.operator import Operator


class _FakeCleanExitProc:
    """Mimics a one-shot watcher subprocess that already exited cleanly."""

    pid = 12345
    returncode = 0

    def poll(self):
        return 0


def _make_operator(tmp_path):
    op = Operator(tmp_path)
    (op.harness_dir).mkdir(parents=True, exist_ok=True)
    return op


def _run_monitor_briefly(op, duration: float, poll_interval: float = 0.02):
    thread = threading.Thread(
        target=op.monitor_and_recover,
        kwargs={"poll_interval": poll_interval},
        daemon=True,
    )
    thread.start()
    time.sleep(duration)
    op._stopping = True
    thread.join(timeout=5)
    assert not thread.is_alive(), "monitor_and_recover did not stop"


def test_clean_watcher_exit_respawn_is_throttled(tmp_path, monkeypatch):
    """A clean (exit 0) watcher must not be respawned on every monitor poll.

    With poll_interval=0.02s and a watcher interval of 0.5s, an unthrottled
    monitor performs dozens of respawns in 0.7s; a throttled one performs
    the initial spawn plus at most 2 interval-gated respawns.
    """
    op = _make_operator(tmp_path)
    op._watcher_respawn_interval = 0.5

    spawn_times: list[float] = []

    def fake_spawn_watcher():
        spawn_times.append(time.monotonic())
        op._watcher_last_spawn = time.time()
        op.processes["watcher"] = _FakeCleanExitProc()

    monkeypatch.setattr(op, "_spawn_watcher", fake_spawn_watcher)
    monkeypatch.setattr(op, "_kill_process", lambda proc, name="": None)

    fake_spawn_watcher()  # initial spawn, as operator start would do
    _run_monitor_briefly(op, duration=0.7)

    respawns = len(spawn_times) - 1
    assert respawns <= 2, (
        f"watcher respawned {respawns} times in 0.7s with a 0.5s interval — "
        "clean exits are being respawned on every monitor poll"
    )


def test_clean_watcher_exit_still_respawns_after_interval(tmp_path, monkeypatch):
    """Throttling must not turn into never-respawning: after the watcher
    interval elapses, a clean-exited watcher is relaunched."""
    op = _make_operator(tmp_path)
    op._watcher_respawn_interval = 0.1

    spawn_times: list[float] = []

    def fake_spawn_watcher():
        spawn_times.append(time.monotonic())
        op._watcher_last_spawn = time.time()
        op.processes["watcher"] = _FakeCleanExitProc()

    monkeypatch.setattr(op, "_spawn_watcher", fake_spawn_watcher)
    monkeypatch.setattr(op, "_kill_process", lambda proc, name="": None)

    fake_spawn_watcher()
    _run_monitor_briefly(op, duration=0.5)

    respawns = len(spawn_times) - 1
    assert respawns >= 1, (
        "watcher was never respawned after a clean exit — throttle is "
        "swallowing respawns entirely"
    )
