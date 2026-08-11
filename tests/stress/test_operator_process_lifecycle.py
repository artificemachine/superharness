"""Iteration 5 of PLAN-prime-agent-adoptions.md — process-lifecycle stress
suite for the operator's historical failure modes.

Regression target: docs/bugs/BUG-2026-06-04-operator-orphans-pytest-swap-storm.md
— a 34.5 GB swap storm caused by (A) a circuit breaker that logged "pausing
restarts for 600s" but kept firing every ~5s, and (B) no process-group
cleanup, so a crashed watcher's own children (pytest, a bridge_worker.js
grandchild) survived as PPID=1 orphans.

Both root causes are already fixed in `engine/operator.py` (`_kill_process`
signals the whole POSIX process group; `monitor_and_recover` gates restarts
on `_circuit_open_until` before touching a component again). Per Resolution
2 (plan section 7): all three scenarios below passed on the first run
against current code. One tightening pass was applied — see the module
docstring on each test for what it hardened — and after that pass they
still all passed. Landed as regression guards: scenarios pass against
current code; they exist to catch a future regression of either bug, not
to reproduce the historical failure.

Safety fence (binding, see PLAN section 2 and Iteration 5's restated
fence): every process spawned here lives under this test's own `tmp_path`;
this module NEVER signals a PID it did not spawn itself, and NEVER touches
the live launchd-managed operator (`com.superharness.operator.*`), the
user's LaunchAgents directory, or the XDG state directory. `pytestmark`
below excludes this whole module from the default `pytest tests/ -q` run
(see the `stress` marker in pyproject.toml); it only runs via
`pytest tests/stress/ -m stress` (locally, or nightly in CI).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from superharness.engine.operator import Operator, _OPERATOR_STATE_FILE
from superharness.engine.process import pid_alive

pytestmark = pytest.mark.stress


_PARENT_WITH_GRANDCHILD = """
import subprocess, sys, time
pidfile = sys.argv[1]
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
with open(pidfile, "w") as f:
    f.write(str(child.pid))
time.sleep(300)
"""


def _wait_until(predicate, timeout: float = 10.0, interval: float = 0.05) -> bool:
    """Poll `predicate` until it is truthy or `timeout` elapses.

    Returns the final predicate value — callers assert on the return value
    so a timeout produces a normal assertion failure, not a bare timeout
    exception with no context.
    """
    deadline = time.monotonic() + timeout
    result = predicate()
    while not result and time.monotonic() < deadline:
        time.sleep(interval)
        result = predicate()
    return result


@pytest.fixture(autouse=True)
def _require_offline_fence():
    """Hard refuse to run this module unless the offline test fence is on.

    This suite spawns and signals real processes; SUPERHARNESS_TEST_OFFLINE
    is set process-wide by tests/conftest.py for the whole suite unless a
    developer opts into SUPERHARNESS_ALLOW_LIVE_TESTS=1. Skip rather than
    silently spawn under a live configuration.
    """
    if os.environ.get("SUPERHARNESS_TEST_OFFLINE") != "1":
        pytest.skip(
            "tests/stress requires SUPERHARNESS_TEST_OFFLINE=1 (safety fence)"
        )


def _operator(tmp_path: Path) -> Operator:
    project_dir = tmp_path / "project"
    (project_dir / ".superharness").mkdir(parents=True)
    return Operator(project_dir)


# ---------------------------------------------------------------------------
# Scenario A (bug B): orphaned grandchild reaped after the watcher is killed
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_orphaned_child_is_reaped_after_parent_kill(tmp_path):
    """Regression guard for bug B (BUG-2026-06-04): a crashed watcher's own
    child must not survive as an orphan.

    Tightening pass: the first version used a bare `time.sleep` child. This
    version spawns a real *grandchild* process (a python subprocess spawned
    BY the watcher-standin, mirroring the real incident shape: watcher ->
    pytest -> bridge_worker.js) and drives the actual production cleanup
    path (`Operator._kill_process`, the shipped fix for bug B) rather than
    a hand-rolled kill. `_kill_process` signals the whole POSIX process
    group (the watcher-standin is its own group leader via
    start_new_session=True, matching `Operator._spawn_watcher`), so the
    grandchild — which inherits that same group — must die too.
    """
    op = _operator(tmp_path)
    script = tmp_path / "watcher_standin.py"
    script.write_text(_PARENT_WITH_GRANDCHILD)
    pidfile = tmp_path / "grandchild.pid"

    parent = subprocess.Popen(
        [sys.executable, str(script), str(pidfile)],
        start_new_session=True,
    )
    try:
        assert _wait_until(pidfile.exists, timeout=10.0), (
            "watcher-standin never wrote the grandchild pidfile"
        )
        grandchild_pid = int(pidfile.read_text().strip())
        assert pid_alive(grandchild_pid), "grandchild never started"
        assert pid_alive(parent.pid), "watcher-standin never started"

        op._kill_process(parent, "watcher")

        assert _wait_until(lambda: not pid_alive(parent.pid), timeout=10.0), (
            f"watcher-standin pid {parent.pid} survived _kill_process"
        )
        assert _wait_until(lambda: not pid_alive(grandchild_pid), timeout=10.0), (
            f"grandchild pid {grandchild_pid} was orphaned by _kill_process "
            "(bug B regression: process-group cleanup did not reach it)"
        )
    finally:
        if pid_alive(parent.pid):
            parent.kill()
            parent.wait(timeout=5)
        try:
            grandchild_pid = int(pidfile.read_text().strip())
        except (OSError, ValueError):
            grandchild_pid = None
        if grandchild_pid and pid_alive(grandchild_pid):
            os.kill(grandchild_pid, 9)


# ---------------------------------------------------------------------------
# Scenario B (bug A): circuit breaker pause actually blocks restarts
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_circuit_breaker_pause_is_enforced(tmp_path):
    """Regression guard for bug A (BUG-2026-06-04): "pausing restarts for
    600s" logged but the watcher kept restarting every ~5s anyway.

    Tightening pass: the first version drove a hand-duplicated copy of the
    loop body (the pattern tests/unit/test_operator_circuit_breaker.py
    already uses for its mocked-process unit tests). This version drives
    the REAL `Operator.monitor_and_recover` entry point in a background
    thread, restarting a REAL subprocess that exits 1 every time (not an
    injected stub), and asserts no further spawn happens once the circuit
    trips.
    """
    op = _operator(tmp_path)
    op._max_restarts = 2
    op._restart_window = 3600  # stays open for the whole test

    spawn_count = 0

    def fake_spawn_watcher():
        nonlocal spawn_count
        spawn_count += 1
        op.processes["watcher"] = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.exit(1)"]
        )

    op._spawn_watcher = fake_spawn_watcher
    fake_spawn_watcher()  # seed the first (crashing) watcher process

    thread = threading.Thread(
        target=op.monitor_and_recover, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        tripped = _wait_until(
            lambda: "watcher" in op._circuit_open_until, timeout=10.0
        )
        assert tripped, "circuit breaker never tripped within the wait window"
        count_at_trip = spawn_count

        # Bug A: the log line said "pausing" but restarts continued every
        # ~5s. Hold well past several poll intervals and assert the spawn
        # count is frozen — no restart happened inside the pause window.
        time.sleep(0.5)
        assert spawn_count == count_at_trip, (
            f"circuit breaker pause was not enforced: spawn_count grew from "
            f"{count_at_trip} to {spawn_count} while the circuit was open "
            "(bug A regression)"
        )
    finally:
        op._stopping = True
        thread.join(timeout=5)
        proc = op.processes.get("watcher")
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Scenario C (PID-file races): singleton state never wedges after SIGKILL
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_pid_file_survives_sigkill_storm(tmp_path):
    """Regression guard for the PID-path bug class named in BUG-2026-06-04
    ("Operator plist still has fragile Python path" / PID-file races more
    generally): after a recorded operator pid is SIGKILLed, the singleton
    check must report "not running" and clear the stale pid — never wedge
    a later `shux operator start` behind a dead PID.

    Tightening pass: the first version SIGKILLed the same process 10 times
    (no-op after the first). This version spawns and kills a fresh real
    process each iteration — a genuine SIGKILL storm across 10 distinct
    pids — and drives the real `Operator._check_singleton` /
    `_write_operator_state` production code, not a re-implementation.
    """
    op = _operator(tmp_path)
    op_file = op.project_dir / _OPERATOR_STATE_FILE

    for i in range(10):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
        try:
            op_file.write_text(
                json.dumps(
                    {
                        "operator_pid": proc.pid,
                        "operator_started_at": time.time(),
                        "project": str(op.project_dir),
                    }
                )
            )

            assert op._check_singleton() is True, (
                f"iteration {i}: live pid {proc.pid} should block a second start"
            )

            proc.kill()  # SIGKILL
            proc.wait(timeout=5)
            assert _wait_until(lambda: not pid_alive(proc.pid), timeout=10.0), (
                f"iteration {i}: pid {proc.pid} never died after SIGKILL"
            )

            assert op._check_singleton() is False, (
                f"iteration {i}: stale pid {proc.pid} still blocks a fresh start"
            )
            remaining = json.loads(op_file.read_text()) if op_file.exists() else {}
            assert "operator_pid" not in remaining, (
                f"iteration {i}: operator_pid was not cleared after the dead-pid "
                f"check — a later start could still be wedged behind it: "
                f"{remaining}"
            )
        finally:
            if pid_alive(proc.pid):
                proc.kill()
                proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Direct unit coverage for the two functions the scenarios above exercise
# ---------------------------------------------------------------------------


def test_breaker_pause_window_math(tmp_path):
    """Unit: the circuit-open deadline is exactly trip_time + restart_window.

    Driven through the real `monitor_and_recover` entry point (mocked
    process, no subprocess — this is the fast/pure counterpart to Scenario
    B's real-subprocess integration test), rather than a hand-duplicated
    copy of the loop's math.
    """
    op = _operator(tmp_path)
    op._max_restarts = 1
    op._restart_window = 100

    proc = mock.Mock()
    proc.poll.return_value = 1
    proc.pid = 999999

    op.processes["watcher"] = proc

    with mock.patch.object(op, "_kill_process", return_value=None), mock.patch.object(
        op, "_spawn_watcher", return_value=None
    ):
        before = time.time()
        thread = threading.Thread(
            target=op.monitor_and_recover, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        try:
            tripped = _wait_until(
                lambda: "watcher" in op._circuit_open_until, timeout=10.0
            )
        finally:
            op._stopping = True
            thread.join(timeout=5)
        after = time.time()

    assert tripped, "circuit breaker never tripped"
    deadline = op._circuit_open_until["watcher"]
    assert before + op._restart_window <= deadline <= after + op._restart_window, (
        f"circuit_open_until={deadline} not within "
        f"[{before + op._restart_window}, {after + op._restart_window}]"
    )


def test_pid_liveness_helper():
    """Unit: Operator._is_pid_alive (delegates to engine.process.pid_alive)
    correctly distinguishes a live process from an exited one."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert Operator._is_pid_alive(proc.pid) is True
        proc.kill()
        proc.wait(timeout=5)
        assert _wait_until(
            lambda: Operator._is_pid_alive(proc.pid) is False, timeout=10.0
        )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
