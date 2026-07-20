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

Side-effect fence: no real daemon is spawned in these tests. The generated
script is asserted on as text; `_stop_daemon`'s process-signalling is
asserted with `os.kill`/`_is_pid_alive` stubbed.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from superharness.commands import daemon as daemon_mod


# ---------------------------------------------------------------------------
# Generated monitor script — adopts the already-spawned watcher
# ---------------------------------------------------------------------------

class TestMonitorAdoptsWatcher:
    def test_monitor_adopts_passed_watcher_pid(self, tmp_path):
        (tmp_path / ".superharness").mkdir()
        script = daemon_mod._write_monitor_script(
            tmp_path, 30, tmp_path / "out.log", tmp_path / "err.log", watcher_pid=4242,
        )
        text = script.read_text()

        assign_idx = text.index("watcher_pid = int(sys.argv[5])")
        # watcher_pid must be referenced again after the argv parse line, as a
        # bare identifier (not just as the "watcher_pid" JSON key name that
        # was already present in the buggy version's write_state()) —
        # previously the parsed value was discarded and never used again.
        rest = text[assign_idx + len("watcher_pid = int(sys.argv[5])"):]
        bare_refs = re.findall(r'(?<!")\bwatcher_pid\b(?!")', rest)
        assert bare_refs, (
            "the generated monitor never references the watcher_pid variable "
            "after parsing it from argv — it will spawn a second watcher "
            "instead of adopting the first"
        )

    def test_monitor_does_not_spawn_before_first_wait(self, tmp_path):
        (tmp_path / ".superharness").mkdir()
        script = daemon_mod._write_monitor_script(
            tmp_path, 30, tmp_path / "out.log", tmp_path / "err.log", watcher_pid=4242,
        )
        text = script.read_text()

        while_idx = text.index("while True:")
        before_loop = text[:while_idx]

        # No unconditional top-level `proc = spawn()` (or equivalent call)
        # before the main loop — the first watcher must come from the
        # adopted watcher_pid, not a fresh spawn() at script startup.
        calls_before_loop = re.findall(r'(?<!def )\bspawn\(\)', before_loop)
        assert not calls_before_loop, (
            f"spawn() is called {len(calls_before_loop)} time(s) before the main "
            f"loop even starts — this is the second-watcher bug"
        )


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
        monkeypatch.setattr(daemon_mod.os, "killpg", lambda pgid, sig: None)
        monkeypatch.setattr(daemon_mod.os, "getpgid", lambda pid: pid)
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
        monkeypatch.setattr(daemon_mod.os, "killpg", lambda pgid, sig: None)
        monkeypatch.setattr(daemon_mod.os, "getpgid", lambda pid: pid)
        monkeypatch.setattr(daemon_mod.os, "kill", lambda pid, sig: None)
        monkeypatch.setattr(daemon_mod, "_STOP_POLL_TIMEOUT_S", 1.0)
        monkeypatch.setattr(daemon_mod, "_STOP_POLL_INTERVAL_S", 0.01)

        state_file = daemon_mod._state_file(tmp_path)
        assert state_file.exists()

        daemon_mod._stop_daemon(tmp_path)  # must not raise

        assert not state_file.exists(), "state file must be removed once both pids are confirmed dead"
        assert alive_calls["monitor"] >= 2, "must have polled until the monitor pid actually died"
