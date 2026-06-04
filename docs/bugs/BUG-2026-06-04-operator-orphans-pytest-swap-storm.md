# BUG: Operator orphans pytest → 34 GB swap storm

**Date:** 2026-06-04
**Severity:** CRITICAL (34.5 GB swap, system near OOM)
**Found by:** OpenCode (opencode) during RAM/swap investigation
**Project:** superharness operator (com.superharness.operator.35dd89d8)

## Symptoms

- Machine swap at 34.5 GB / 35 GB (96%), up from 13.8 GB 1h earlier
- `memory_pressure` reported only 36% free memory
- One `python3 -m pytest tests/unit/` process (PID 3997) consuming 10.7 GB RSS,
  PPID=1 (orphaned), running in `/Users/airm2max/DevOpsSec/trayzury`
- Child process: `node bridge_worker.js` (PID 4301, 50 MB)
- Superharness log flooded with circuit breaker errors (see below)

## Root Cause Chain

### 1. Operator watcher crash loop (118 restarts / 600s)
```
2026-06-04T16:11:57+0200 ERROR operator.py: circuit breaker TRIPPED for watcher
— 118 restarts in 600s. Pausing restarts for 600s.
```
This message repeats every **5 seconds** from 16:11 onward — the circuit breaker
fires, says it's pausing, but immediately fires again. The pause is not enforced.

### 2. Watcher spawns pytest that becomes orphan
When the watcher restarts, it (or a prior run) spawns `pytest tests/unit/` in
trayzury. When the watcher crashes again, the pytest's parent dies and launchd
adopts it (PPID=1). The pytest keeps running, loading test data, spawning a
`bridge_worker.js` child, and growing to 10.7 GB RSS.

### 3. Swap balloons to 34.5 GB
macOS pushes the pytest's memory pages to swap. The pytest's RSS drops from
10.7 GB → 6.4 GB as pages move to swap, but swap grows from 13.8 GB → 34.5 GB.
macOS auto-expands the swap file from 15 GB to 35 GB.

### 4. Reaper doesn't cover pytest
`claude-session-reaper.sh` has rules for:
- Superharness workers (inbox_watch, dashboard-ui, operator)
- MCP servers (hablatone, serena, obsidian-semantic, etc.)
- Dev servers (astro, vite, etc.)
- Loky/joblib workers

But **no rule for pytest or generic test runners**. The orphaned pytest survives
even after a reaper run.

## Fix (immediate, already applied)

Killed PID 3997 (pytest) + child 4301 (bridge_worker.js). Result:

| Metric | Before | After |
|--------|--------|-------|
| Swap used | 34,476 MB | 2,771 MB |
| Swap total | 35,840 MB | 4,096 MB |
| Memory free | 36% | 87% |

**31.7 GB swap freed by killing one process.**

## Bugs to Fix

### A. Broken circuit breaker (`operator.py:monitor_and_recover:322`)
The circuit breaker prints "Pausing restarts for 600s" but fires again 5 seconds
later. The pause is a no-op — the watcher keeps restarting indefinitely.

- **Expected**: After tripping, the circuit breaker should actually sleep for
  600s before attempting another restart.
- **Actual**: The message logs every ~5s, meaning the pause is not blocking.

### B. No child-process lifecycle management
When the operator or its watcher crashes, any child processes it spawned (pytest,
node, etc.) are abandoned as orphans. The operator should:
- Track child PIDs
- Kill them on shutdown/crash (`atexit` handler or `SIGTERM` handler)
- Set a timeout for test runs and kill them if exceeded

### C. Reaper missing pytest / test-runner coverage
`claude-session-reaper.sh` should detect and kill orphaned test runners:
- `pytest`
- `python -m pytest`
- `python -m unittest`
- `jest`
- Any process with PPID=1 and RSS > 500 MB that's not whitelisted

### D. Operator plist still has fragile Python path
`com.superharness.operator.35dd89d8.plist` uses:
```
/Users/airm2max/.pyenv/shims/python3
```
It works by accident (the shim resolves) but will break after any
`pipx reinstall superharness` — same bug as June 1 (vault note:
`2026-06-01-superharness-operator-storm.md`). Should be:
```
/Users/airm2max/.local/pipx/venvs/superharness/bin/python
```

## Reproduction

Not attempted (destructive). Likely trigger: operator watcher encounters an
error in trayzury's test suite, crashes, restarts, spawns another pytest,
crashes again — pytest accumulates.

## Evidence

- `~/Library/Logs/superharness/superharness.log` — circuit breaker flood (50+ lines
  @ 5s intervals from 16:11 to 16:16+)
- Process snapshot at 15:46: PID 3997 (pytest, 10.7 GB RSS, PPID=1, cwd=trayzury)
  with child PID 4301 (bridge_worker.js)
- Swap history: 13.8 GB (15:46) → 34.5 GB (16:11) → 2.8 GB (16:17, after kill)

## Related

- `REPORT-process-leak-2026-05-28.md` — prior superharness process leak (1,418 processes)
- `notes/ephemeral/sessions/2026-06-01-superharness-operator-storm.md` — operator crash loop from wrong Python path
- `notes/ephemeral/sessions/2026-05-28-ram-optimization-ollama-consolidation.md` — RAM investigation
