# Watcher Dies Between Sessions — Root Cause Report

**Date:** 2026-05-27  
**Project:** superharness v1.67.0  
**Repro:** `shux operator start` → watcher ∎ after bash tool session ends

---

## Symptom

Every `shux status` check after a few minutes shows:

```
watcher: level=bad not loaded, heartbeat stale (last heartbeat 229m ago)
heartbeat: stale (last heartbeat 229m ago)
```

Must repeatedly run `shux operator start` to revive it.

---

## Root cause

**`shux operator start` is a foreground blocking process with no daemonization.** It calls `monitor_and_recover()` which runs an infinite `while True` loop (`cli.py:604`). When the invoking shell session terminates, the entire process tree dies — watcher, dashboard, monitor, all of it.

```
cli.py:596-604 (operator_start)
    op.start_stack(...)        # spawns watcher + dashboard subprocesses
    op.monitor_and_recover()   # infinite while loop — BLOCKS FOREVER
```

In the opencode/claude-code `bash` tool, the command is run with `&` to background it, but the tool's subprocess timeout kills the session, taking the operator + watcher + dashboard with it.

---

## The launchd gap

`shux operator install` was designed to solve this by creating a persistent launchd plist. It was **never run** for the nemorad project.

### What exists (broken)

```
~/Library/LaunchAgents/com.superharness.operator-watchdog.plist  ← exists, runs heal every 5 min
launchctl: com.superharness.operator-watchdog                    ← loaded, pid 0 (exited)
```

The watchdog runs `shux operator heal --quiet` every 300s. But `heal` only checks "is there an operator plist on disk? if yes, bootstrap it." Since no operator plist exists, `heal` does nothing.

### What's missing (should exist)

```
~/Library/LaunchAgents/com.superharness.operator.<hash>.plist    ← MISSING
launchctl: com.superharness.operator.<hash>                      ← MISSING
```

Without the operator plist, there is no persistent process to keep the watcher alive.

---

## The install never happened

| Step | Status |
|------|:---:|
| `shux operator install` run for nemorad | ❌ never run |
| Operator plist created | ❌ |
| Operator plist loaded into launchd | ❌ |
| Watchdog plist exists (from prior install) | ✅ (but idle — nothing to heal) |
| `shux operator start` used as workaround | ✅ (dies every session) |

---

## The full chain

```
1. User runs `shux operator start &`
2. Operator spawns watcher + dashboard subprocesses (start_new_session=True)
3. Operator enters monitor_and_recover() infinite loop
4. Bash tool session ends or times out → SIGTERM/SIGKILL
5. Operator process dies (it was in foreground, not daemonized)
6. Watcher + dashboard subprocesses become orphans → re-parented to launchd
7. launchd eventually reaps orphaned processes
8. watchguard watchdog fires every 5 min → runs `shux operator heal`
9. heal checks for operator plist → not found → "nothing to do"
10. Watcher stays dead until next manual `shux operator start`
```

---

## Why `start` isn't a daemon

The design intent (from `operator.py:145` comment) is:

> Runs in a daemon thread (spawned by operator_start in cli.py) so the CLI returns immediately.

But the implementation contradicts the comment: `monitor_and_recover()` is called directly in the main thread, blocking `operator_start` forever. The CLI never returns. The "daemon thread" comment refers to the *SDK runner* above it (line 538 — a different command), not to `operator_start`.

---

## Fix

### Immediate (one-shot)

```bash
shux operator install --project nemorad
```

This creates + loads:
- `com.superharness.operator.<hash>.plist` → persistent operator plist, KeepAlive=true
- The existing watchdog will then be able to heal it if it ever crashes

### Deeper (code fix for `operator_start`)

**Applied 2026-05-27:** Option A implemented. `operator_start` now daemonizes via fork+setsid by default. The parent process returns immediately; the child detaches from the terminal, redirects stdio to /dev/null, and runs the monitor loop. The watcher survives the invoking shell session.

Use `--no-daemon` to run in foreground for debugging.

Two options were considered:

**Option A — Daemonize operator_start (so `start` is self-sufficient)**
Fork + detach before entering `monitor_and_recover()` so the CLI returns and the watcher lives independently of the invoking shell.

```python
def operator_start(project, port, no_open):
    # ... spawn watcher + dashboard ...
    if os.fork():          # parent returns
        return
    os.setsid()            # child detaches
    op.monitor_and_recover()
```

**Option B — Make the comment true**
Move `monitor_and_recover()` into a daemon thread so the CLI returns immediately while the monitor loop keeps running in the background.

```python
t = threading.Thread(target=op.monitor_and_recover, daemon=False)
t.start()
# CLI returns, thread keeps watcher alive
```

Option B is simpler and matches the existing comment. Option A is the traditional Unix approach. Either would fix the "dies between sessions" problem without requiring `install`.

---

## Impact

**Fixed.** `shux operator start` now daemonizes. The watcher survives shell session termination. For production persistence, still run `shux operator install` to create a launchd plist with KeepAlive.
