# AUDIT: Dashboard Management Architecture

## Current State Analysis

The dashboard respawns because it is a **managed component of the Superharness Operator**. When the operator is running (either in the foreground or as a `launchd` service), it actively monitors its subprocesses and automatically restarts the dashboard (and the watcher) if they exit or are killed.

### Technical Root Cause

The `superharness.engine.operator.Operator` class implements a `monitor_and_recover` loop that polls its child processes every 5 seconds. If it detects that the `dashboard` process is missing, it triggers `_spawn_dashboard` to bring it back.

When the operator is installed as a service (e.g., via `shux operator install`), the `launchd` plist is configured with `KeepAlive: true`. This means:

1.  **launchd** ensures the **Operator** is always running.
2.  **The Operator** ensures the **Dashboard** is always running.

## Architectural Evaluation

Tightly coupling a UI server (Dashboard) with a background worker (Watcher) is a design anti-pattern for several reasons:

1.  **Violation of Separation of Concerns:** The "Operator" is currently a monolith that manages both task execution and UI. A failure in the Dashboard's HTTP server logic shouldn't technically require the same "Guardian" logic that keeps the core task-dispatching loop alive.
2.  **Resource Waste:** Running a web server 24/7 on every project where a background operator is active is inefficient, especially in "headless" or server environments.
3.  **Inflexible Process Hierarchy:** By having a Python parent (`operator.py`) manage subprocesses, ability to manage them independently via standard OS tools (like `launchctl` or `systemctl`) is lost.
4.  **Implicit State:** The dashboard is treated as "part of the engine" rather than an optional "view into the engine."

## Proposed Improvement: Decoupling

A more robust architecture decoupling would involve:

1.  **`com.superharness.watcher`**: A headless background service that only runs the task loop (`inbox_watch`).
2.  **`com.superharness.dashboard`**: An on-demand or separate service that only runs the UI.

### Immediate Action: `--no-dashboard` Flag

To provide immediate relief, a `--no-dashboard` flag should be implemented for `shux operator start` and `shux operator install`. This allows running the "Guardian" logic for the watcher only, which is ideal for persistent background work without the UI overhead.
