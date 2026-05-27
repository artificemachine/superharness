# Gemini-CLI Discussion Dispatch Fails Silently — Round Never Submitted

**Date:** 2026-05-27  
**Version:** superharness v1.67.0  
**Project:** nemorad  
**Discussion:** `discuss-20260527T111318Z-51830-254439277`

---

## Symptom

Gemini-cli was dispatched for discussion round 2 but never submitted a response. The discussion was eventually marked `failed_participant` by the watcher. No error surfaced in any log, watcher dashboard, or `shux status`.

**Timeline (from audit log):**

```
13:18:09  claude-code   dispatched  round 1  ✅ submitted
13:18:14  gemini-cli    dispatched  round 1  ✅ submitted  
13:18:20  opencode      dispatched  round 1  ✅ submitted

17:08:36  claude-code   dispatched  round 2  ✅ submitted  (7,066 char prompt)
17:08:41  opencode      dispatched  round 2  ✅ submitted  (7,057 char prompt)
17:12:40  gemini-cli    dispatched  round 2  ❌ NEVER RETURNED  (7,063 char prompt)
         → no round-2-gemini-cli.yaml written
         → no error in superharness.log, audit.log, or operator logs
```

---

## Investigation

### Dispatch confirmed

The audit log (`superharness-audit.log`) confirms gemini-cli was launched:

```
2026-05-27T17:12:40+0200 INFO superharness.audit dispatch:
  target=gemini-cli
  project=/Users/airm2max/DevOpsSec/nemorad
  non_interactive=True
  model=gemini-2.5-pro
```

The superharness log matches:

```
2026-05-27T17:12:40+0200 INFO superharness.delegate launch_agent
  target=gemini-cli prompt_len=7063
```

### No error anywhere

| Log checked | Result |
|-------------|--------|
| `superharness.log` | Launch logged, no error |
| `superharness-audit.log` | Dispatch logged, no failure |
| `com.superharness.operator.*.err.log` | Empty |
| `com.superharness.operator.*.out.log` | Routine operator cycling |
| Watcher heartbeat | Healthy |
| SQLite `failures` table | No gemini rows |
| SQLite `ledger` table | No gemini failure events |
| YAML round files | `round-2-gemini-cli.yaml` absent |

### Operator was crash-looping during dispatch

The operator PIDs cycled 12+ times in the window around gemini's dispatch:

```
... 59955 → 60859 → 62214 → 63315 → 64021 → 65083 →
    65905 → 67064 → 68347 → 69721 → 70965 → 72154 ...
```

Gemini was launched by PID 69721 of the operator's watcher. Fifteen seconds later, the operator restarted (PID 70965). The `start_new_session=True` flag was set on the subprocess.Popen for the watcher, so the gemini process itself should not have been killed. But the watcher that was tracking gemini's completion status was gone. A new watcher spawned under the new operator may not have correctly correlated the orphaned gemini process with the discussion round.

### Gemini CLI is functional

- Binary: `/Users/airm2max/.nvm/versions/node/v25.2.1/bin/gemini` (v0.43.0)
- Round 1 submission succeeded (submitted at 2026-05-27T11:20:00Z)
- The binary was available on PATH throughout

---

## Contributing factors

1. **Operator crash-fest**: The operator was in a rapid restart cycle because `shux operator start` (foreground, no daemonization) was being repeatedly kill-restarted by the bash tool timeout + watchdog heal combo. Each cycle spawned a new watcher that was a fresh process with no knowledge of the prior watcher's in-flight dispatches.

2. **No orphan tracking**: When a watcher crashes, there is no mechanism to reconnect new watchers to previously-dispatched-but-unfinished agent processes. The `start_new_session=True` flag keeps the gemini process alive, but the new watcher has no PID reference to it.

3. **No dispatch timeout log**: The 900s discussion round timeout applies to the watcher's `subprocess.run()` call, but there is no log entry when it fires. If gemini timed out, we would expect at least a TIMEOUT or KILLED trace in the watcher output. We see nothing — suggesting the process may have been silently orphaned rather than timed out.

4. **No retry for discussion rounds**: After the watcher marked gemini as `failed`, the discussion went straight to `failed_participant`. There was no retry dispatch, even though gemini's retry budget was not exhausted (the launch itself may have never been recorded as a failed attempt since the tracking watcher died).

5. **Silent failure surface**: The combo of (orphaned process) + (no error log) + (no retry) + (no dashboard alert) means this failure was invisible until a human checked `shux status`.

---

## Impact

The discussion lost one of three agent perspectives for round 2. The remaining two agents (opencode + claude-code) reached strong consensus (9 of 12 points agreed, aligned order of operations), so the outcome was not severely degraded. But in a tighter discussion where gemini was the tiebreaker or held a unique position, this would have produced deadlock or a lower-quality synthesis.

---

## Recommended fixes

### Applied 2026-05-27

1. **Log timeout kills** ✅ — Discussion round timeouts now log at ERROR level with agent/discussion/round details.
2. **Orphan recovery** ✅ — `_recover_orphaned_dispatches()` runs at the start of each poll cycle. Marks stuck inbox items (launched/running, no heartbeat for >15min) as failed so the retry mechanism picks them up.
3. **Operator daemonization** ✅ — `operator_start` now fork+setsid detaches. Watcher survives shell session termination. No more crash loops.

### Remaining

4. **Dispatch watchdog PID file** — Record expected PID and heartbeat path per dispatch. If watcher restarts, new watcher reads the file and reconnects to surviving orphan processes. (Medium-term)

---

## Raw evidence

### Audit log (relevant entries only)

```
2026-05-27T17:08:36+0200 INFO dispatch: target=claude-code model=claude-sonnet-4-6
2026-05-27T17:08:41+0200 INFO dispatch: target=opencode model=deepseek-v4-flash
2026-05-27T17:12:40+0200 INFO dispatch: target=gemini-cli model=gemini-2.5-pro
```

### Round file listing

```
round-1-claude-code.yaml  7.4K  ✅
round-1-gemini-cli.yaml   1.7K  ✅
round-1-opencode.yaml     13.1K ✅
round-2-claude-code.yaml  8.1K  ✅
round-2-opencode.yaml     14.0K ✅
round-2-gemini-cli.yaml   —     ❌ (never written)
```

### Discussion final state

```
discussions: active=0 consensus=0 failed_participant=1 deadlock=0 closed=3
tasks: archived=12 (discussion auto-archived)
```

---

## Severity

**Medium.** Lost one agent's contribution to a discussion round. No data loss, no system crash, no user impact beyond delayed awareness. The underlying bug (orphan dispatch during operator cycling) could cause more severe failures if it hits at a critical consensus round or during a low-agent-count discussion (2 agents, one fails → deadlock).
