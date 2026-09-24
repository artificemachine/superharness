# Superharness Process Leak — Incident Report
**Date:** 2026-05-28
**Severity:** HIGH — 11.5 GB RAM consumed, machine in swap (5.67 GB)

---

## Summary

Superharness has accumulated **1,418 orphaned Python processes** consuming **11.5 GB RSS**
(~40% of total physical RAM). The primary trigger is the `nemorad` project, where three
worker types are spawning uncontrolled and never being reaped. The machine is in swap as a
direct result.

---

## Process Inventory

| Worker type | Total count | Nemorad count | Notes |
|---|---|---|---|
| `dashboard-ui` | 440 | 430 | One per shux session, never killed |
| `inbox_watch` | 419 | 418 | One per agent dispatch, leaks on cmux close |
| `operator start` | 432 | ~430 | Spawning every ~1 min, active runaway loop |
| Other (daemon-monitor, tail, etc.) | ~127 | mix | Session artifacts |
| **Total** | **1,418** | **~1,278** | **11.5 GB RSS** |

Oldest surviving process: **12 days** (`dashboard-ui` for `open-generative-ai`, PID 80850).

---

## Root Cause Analysis

### 1. `operator start` — active runaway loop (CRITICAL)

The `nemorad` project has a live loop spawning a new `operator start` process every ~60 seconds.
Evidence from process start times:

```
6:31PM, 6:32PM, 6:33PM, 6:34PM, 6:35PM, 6:36PM, 6:37PM, 6:38PM, 6:39PM ...
```

This suggests either:
- A cron, launchd job, or watcher script that unconditionally calls `shux operator start`
  without checking whether one is already running.
- A crash-restart loop where the operator exits and the launcher respawns it immediately.

Each new instance adds ~8-10 MB RSS. At one per minute over 8 hours, that is 480+ processes
and ~4 GB of RAM from this cause alone.

### 2. `dashboard-ui` — no singleton enforcement

Every `shux status`, `shux monitor`, or agent spawn that opens the dashboard starts a new
`dashboard-ui` process on incrementing ports (8787, 8788, 8789 ... 8797 observed). There is
no check for an existing instance, no PID file, and no cleanup on cmux pane exit.

430 instances are bound to `nemorad` alone. They do not die when the cmux pane closes
because they have no controlling terminal (`tty == ??`).

### 3. `inbox_watch` — orphaned on session exit

`inbox_watch` workers are started per agent dispatch. When a cmux pane closes without
graceful shutdown, the worker is orphaned. The existing `claude-session-reaper.sh` only
kills inbox_watch workers whose `--project` path is in `/tmp/` or no longer exists on disk.
Since `nemorad` is a live project at a valid path, 418 workers survive indefinitely.

### 4. Reaper blind spots

`claude-session-reaper.sh` does not cover:
- `dashboard-ui` processes (not in its pattern list at all)
- `operator start` processes
- Duplicate `inbox_watch` workers for live projects (only kills missing-project ones)

---

## Affected Projects

| Project | dashboard-ui | inbox_watch | operator |
|---|---|---|---|
| nemorad | 430 | 418 | ~430 |
| synod | 2 | 1 | - |
| scalping_bot | 2 | - | - |
| workspace root | 2 | - | - |
| trayzury | 1 | - | - |
| superharness | 1 | - | - |
| open-generative-ai | 1 | - | - |
| morpheme | 1 | - | - |

`nemorad` is the epicenter — 90%+ of leaked processes belong to it.

---

## Impact

| Metric | Value |
|---|---|
| Superharness processes | 1,418 |
| RAM consumed (RSS) | 11.5 GB |
| Machine RAM | 32 GB |
| Total RAM used | 28.35 GB |
| Swap used | 5.67 GB |
| Machine state | Active swap — performance degraded |

The swap usage means macOS is compressing and evicting pages. Real-world impact: slowdowns
when switching between apps, IDE lag, and potential kernel panics under further pressure.

---

## Immediate Remediation

Kill all accumulated workers now:

```bash
# Stop the runaway operator loop first
pkill -f "superharness.cli operator"

# Kill all dashboard-ui instances
pkill -f "superharness.scripts.dashboard-ui"
pkill -f "superharness/scripts/dashboard-ui.py"

# Kill orphaned inbox_watch workers
pkill -f "superharness.commands.inbox_watch"

# Verify
ps aux | grep superharness | grep -v grep | wc -l
# Expected: < 5 (only the daemon-monitor and any intentionally running instances)
```

Expected RAM reclaim: **8-11 GB**, enough to clear swap.

---

## Required Fixes

### Fix 1 — Find and stop the operator respawn trigger

Identify what is calling `shux operator start` every minute for nemorad:

```bash
# Check launchd jobs
launchctl list | grep -i nemorad
launchctl list | grep -i superharness

# Check crontab
crontab -l | grep -i nemorad

# Check if nemorad has a daemon-monitor or watcher that auto-restarts
ls nemorad/.superharness/
```

The operator loop must be idempotent: if an instance is already running, refuse to start
another. A PID file at `.superharness/operator.pid` with a liveness check is sufficient.

### Fix 2 — Singleton enforcement for `dashboard-ui`

Before spawning a new dashboard-ui, check for an existing one on the same project:

```bash
existing=$(pgrep -f "dashboard-ui.*--project $PROJECT_PATH")
if [[ -n "$existing" ]]; then
    # just open the browser tab, don't spawn a new process
    open "http://localhost:$PORT"
    exit 0
fi
```

Or use a PID file at `.superharness/dashboard.pid`.

### Fix 3 — Extend `claude-session-reaper.sh` to cover all worker types

Add these patterns to the reaper's candidate scan:

```bash
# dashboard-ui — kill duplicates beyond the first per project
# operator start — kill all instances older than MIN_AGE if a newer one exists
# inbox_watch — kill ALL orphaned workers for live projects (not just missing paths)
```

A simpler approach: add a `shux stop-all` command that kills every worker for a project
and hook it into cmux pane-exit via `set-hook pane-died`.

### Fix 4 — Monitor for future leaks

Add a launchd job or cron that alerts when superharness process count exceeds a threshold:

```bash
# ~/.local/bin/superharness-watchdog
count=$(pgrep -f superharness | wc -l | tr -d ' ')
if [[ $count -gt 20 ]]; then
    terminal-notifier -title "Superharness Leak" \
        -message "$count processes running — run pkill -f superharness" \
        -sound Basso
fi
```

---

## Related

- `~/scripts/claude-session-reaper.sh` — existing reaper (needs extension)
- `~/scripts/auto-cleanup.sh` — disk cleanup (does not touch processes)
- Vault: `notes/devops/2026-04-06-Docker-OrbStack-RAM-Cleanup.md` — prior RAM incident
- `/orphan-guard` skill — machine-scoped orphan audit
