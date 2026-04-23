# Project Handoff: The Headless Future (v1.31.0)

**Date**: 2026-04-23  
**Status**: Engine Stable / 100% Autonomous  
**Summary**: Successfully transitioned Superharness from a manual, agent-specific CLI tool into a registry-driven, self-healing autonomous engine.

---

## 🚀 Key Achievements

### 1. The Superharness Operator (Guardian)
*   **What**: A new watchdog process (`shux operator`) that manages the background stack.
*   **Self-Healing**: It automatically detects if the Watcher or Dashboard crashes and restarts them.
*   **Port Arbitration**: Automatically resolves port 8787 conflicts by finding the next available port.
*   **Status**: Production-ready and verified with integration tests.

### 2. Registry-Driven Multi-Agent Support
*   **Native Gemini**: Officially integrated **Gemini CLI** with its own manifest and launcher.
*   **Exclusive Ownership**: Hardened `inbox.py` to prevent "Double-Agent" race conditions. A task can only have one active entry in the inbox at a time.
*   **Manifest Standard**: All agents (Claude, Codex, Gemini) now use a versioned model tier schema.
*   **Model Routing**: Fixed the bug where Gemini would default to "sonnet" in backend logs.

### 3. Dashboard Modernization
*   **Standardized UI**: Implemented a professional 140x36px action grid and 6px pill buttons.
*   **Live Task Reports**: Fixed real-time terminal streaming. Users can now see agent logs as they happen without technical ANSI clutter.
*   **Intelligent Filtering**: The dispatch queue now defaults to showing only "Active" tasks, hiding historical failures.

---

## 📊 Current Roadmap Status

| Task ID | Status | Agent | Outcome |
| :--- | :--- | :--- | :--- |
| `chore.collapse-guards-next-action` | ✅ **DONE** | Claude | Centralized all guard tables into `next_action.py`. |
| `verify.auto-dispatch.A/B/C` | ✅ **DONE** | Gemini | Verified the "Domino Effect" (cascading dispatch chain). |
| `feat.dashboard-auto-restart` | 🏃 **ACTIVE** | Claude | Implementing auto-restart when engine version changes. |

---

## 🛠 Next Actions for the Operator

1.  **Autonomous Review**: Use the new `report_ready` status to have Gemini peer-review Claude's recent refactor.
2.  **Notification Layer**: Implement **Desktop/Telegram notifications** for the Guardian so it can alert you when a task finishes or a budget is hit.
3.  **Auto-Stash**: Implement `feat.dispatch-auto-stash` so the autonomous engine can work even if you leave the project with a dirty worktree.

---

## ⚠️ Infrastructure Note
When starting a new session, always run:
```bash
shux operator start --port 8787
```
This initializes the Guardian and ensures the background worker has the correct `PYTHONPATH` for your local fixes.
