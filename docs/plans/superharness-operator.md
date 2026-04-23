# Design Plan: Superharness Operator (v1.32.0)

To ensure high availability and self-healing for autonomous work, Superharness requires an **Operator (Watchdog)** process that manages the lifecycle of the system components themselves.

## Goal
The Operator is the "Guardian" of the Superharness stack. It ensures that the Watcher and Dashboard are always running, healthy, and not conflicting with each other.

---

## Iteration 1: The Watchdog (Heartbeat & Zombies)
*   **RED**: Add `tests/unit/test_operator_watchdog.py`. Verify it detects a stale heartbeat (based on `.superharness/heartbeat.yaml`) and correctly identifies "zombie" Python processes holding the project lock.
*   **GREEN**: Implement `shux operator check`. It scans the heartbeat and project files. It identifies if the system is "hung."
*   **REFACTOR**: Centralize PID-tracking logic into a shared helper used by both the Operator and the Dashboard.

## Iteration 2: The Process Manager (Auto-Restart)
*   **RED**: Add `tests/integration/test_operator_recovery.py`. Mock a watcher crash (delete PID) and verify the operator re-spawns it.
*   **GREEN**: Implement `shux operator start`. It launches the Watcher and Dashboard in a managed process group. If either process exits with a non-zero code, the Operator re-launches it (with an exponential backoff).
*   **REFACTOR**: Use `subprocess.Popen` groups to ensure `SIGTERM` propagates correctly to all children.

## Iteration 3: The Port Arbitrator (Conflict Resolution)
*   **RED**: Add `tests/integration/test_port_arbitration.py`. Simulate another process using port 8787. Verify the operator detects this and chooses 8788.
*   **GREEN**: Update `shux operator start` to check port availability before launching the Dashboard. Update the local project metadata (`daemon.pid.json`) with the active port so CLI tools know where the dashboard is.
*   **REFACTOR**: Finalize the `shux status` output to show "Guardian: Level=ok" indicating the Operator is active.

---

## Technical Specs
*   **Module**: `src/superharness/engine/operator.py`
*   **Command**: `shux operator {start|stop|status|check}`
*   **Metadata**: Store state in `.superharness/operator.yaml`.
*   **Graceful Exit**: Operator must clean up all child processes (Watcher/Dashboard) before exiting.
