# AUDIT: Headless-First Architecture & Dashboard Decoupling

## Overview
The Superharness engine has been refactored to prioritize resource efficiency and separation of concerns. The "Operator" stack, previously a monolith of UI and worker processes, is now **headless by default**.

## Key Changes

### 1. Headless Operator Stack
- **Default Behavior:** `shux operator start` and `shux operator install` now only start the core background **Watcher**.
- **Opt-in UI:** To run a persistent dashboard managed by the operator, the `--dashboard` flag must be used.
- **Rationale:** Prevents unnecessary web servers and browser spawns in CI/CD or server environments while maintaining background task processing.

### 2. On-Demand Dashboard with Auto-Timeout
- **Lease Pattern:** Standalone dashboards (`shux dashboard`) now support a `--timeout` flag (defaulting to 0/disabled, but encouraged for interactive use).
- **Heartbeat:** The UI sends periodic pings to the server. If pings stop (tab closed or user idle for 5+ min), the server shuts down automatically.
- **Visual Feedback:** A warning banner appears 60 seconds before session expiration.

### 3. Engine Reliability
- **Process Cleanup:** The `operator.py` component was hardened to prevent process leakage when switching between headless and dashboard-enabled modes.
- **Port Reuse:** Port arbitration logic ensures that on-demand dashboards don't "inflate" port numbers (e.g., 8787 -> 8788) when stale processes exist.

## Verification State
- **Automated Tests:** `tests/test_dashboard_timeout.py` verifies the exit logic and keep-alive heartbeats.
- **Manual Audit:** Confirmed that `shux operator install` creates a `launchd` service that runs without spawning a `dashboard-ui` process.

## Command Reference (v1.69.5+)
| Command | State |
|---------|-------|
| `shux operator start` | Watcher ONLY |
| `shux operator start --dashboard` | Watcher + Dashboard |
| `shux dashboard` | On-demand UI (Standalone) |
| `shux dashboard --timeout 300` | UI with 5-min auto-cleanup |
