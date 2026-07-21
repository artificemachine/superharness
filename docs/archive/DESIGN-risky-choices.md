# Risky Design Choices

Documented here so contributors understand the architecture's sharp
edges before they trip on them. Each choice has context on why it
exists and the failure mode it creates.

---

## 1. Auto-Actions Without Cooldown

**Pattern**: All `auto_*` functions run every watcher tick (3s). No
"last ran at" check, no per-action throttle.

**Why it exists**: The watcher is designed as a simple polling loop.
Adding per-action timers was deferred.

**Failure mode**: If action A's output triggers action B, and B's
output triggers A, you get a cascading loop at 3s intervals. Same
root cause behind 3 bugs fixed in v1.52-1.54 (retry loop, escalate
loop, bootstrap ping-pong).

**Mitigation**: Auto-bootstrap and permanent-block recovery now
target `waiting_input` (not `todo`), which stops auto-dispatch.
But new auto-actions must be audited for feedback loops.

---

## 2. Retry as Default Pattern

**Pattern**: `profile.yaml` ships with `auto_retry: true`. Every
failure gets N retries with zero operator notification.

**Why it exists**: The system targets autonomous operation.
Transient failures (network, quota) should self-resolve.

**Failure mode**: A permanent failure (lifecycle gate, missing
content) × 3 retries × 3s tick = 9 dispatch attempts before the
operator sees anything. Combined with #1, this becomes an
amplifier for any loop bug.

**Mitigation**: v1.54 added retry-count incrementing (was stuck
at 0) and decision ledger recording. Permanent blocks now
escalate to `waiting_input` after retries exhausted.

---

## 3. Failed Reason as Ephemeral

**Pattern**: `failed_reason` is a single TEXT column. It gets
cleared on retry. There is no append-only failure log by default.

**Why it exists**: Simplicity. One reason per attempt, last
attempt's reason is the one that matters (in theory).

**Failure mode**: If a failure is transient on attempt 1 but
permanent on attempt 3, the operator sees only attempt 3's
reason. Attempt 1's diagnostic is lost. Combined with #2,
most failures are invisible.

**Mitigation**: v1.54 preserves the original reason through
retries. The decision ledger (ledger_dao) is the append-only
log, but it's fire-and-forget and not queried by default.

---

## 4. SQLite as Passive Sink

**Pattern**: Every component writes to SQLite, but no component
uses SQLite as a coordination point. No row-level locking, no
`SELECT FOR UPDATE`, no advisory locks.

**Why it exists**: The system was ported from YAML files to SQLite.
The YAML access pattern (read-modify-write with file locks) was
translated to SQL, not redesigned for database semantics.

**Failure mode**: Two watchers on the same project could claim
the same inbox item. Currently mitigated by PID tracking in
the inbox row, but this is application-level, not ACID-level.
A crashed watcher leaves PID garbage.

**Mitigation**: The `claim_next` DAO method updates status within
a transaction, but there's no `SELECT ... FOR UPDATE SKIP LOCKED`
for true queue semantics.

---

## 5. Status as a String, Not a State Machine

**Pattern**: Task statuses are free-text strings. Comparison is
`status == "todo"`. There's no enum, no transition table at the
data layer, no compile-time exhaustiveness check.

**Why it exists**: Started as YAML keys, ported to SQL TEXT.
Adding a new status is one line — very agile during prototyping.

**Failure mode**: A typo in any of ~30 check sites silently fails
(the status just doesn't match, no error). Adding a new status
requires finding every `== "oldstatus"` site. Currently 16
statuses × ~30 check sites = 480 failure points.

**Mitigation**: `engine/next_action.py` centralizes the allowed
transitions, but the storage layer has no enforcement. `waiting_input`
was added in v1.54 and required patching 5 files.

---

## 6. Subprocess as Interface Boundary

**Pattern**: The dispatcher invokes the delegate as a subprocess:
`python -m superharness.commands.delegate --task X --project Y`.
All error handling depends on exit codes.

**Why it exists**: Process isolation. A crashing agent shouldn't
take down the watcher. The delegate can run arbitrary code safely.

**Failure mode**: Exit codes only cover intentional failures.
Signal deaths (SIGKILL, SIGSEGV) produce exit code -N or 128+N
depending on shell, which none of the handlers check for. Only
exit 124 (timeout) and exit 2 (permanent block) have dedicated
handlers.

**Mitigation**: The failure classifier in `failure_classifier.py`
handles unknown exit codes with a catch-all, but the subprocess
caller (`inbox_dispatch.py:1045`) doesn't distinguish between
"subprocess crashed" and "subprocess exited gracefully".

---

## 7. No Budget/Governor

**Pattern**: Nothing limits how many inbox items the watcher can
create per tick. No rate limiting, no queue depth cap, no circuit
breaker.

**Why it exists**: During normal operation, the watcher creates
~1 item per tick. The capacity was designed for throughput.

**Failure mode**: A loop bug (like the permanent-block cycle)
can generate thousands of inbox items before anyone notices.
One test task (`tb3`) generated 854 failed items in a few
minutes during development.

**Mitigation**: `loop_guard_state.json` tracks consecutive
failures, but it's a flat file with no integration into the
enqueue path. A proper circuit breaker would reject enqueue
when `recent_failures > threshold`.

---

## 8. No Stale Active Discussion Timeout

**Pattern**: `active` discussions have no auto-timeout. Only
`consensus` discussions auto-close (after 60 minute grace period).

**Why it exists**: Active discussions should have live
participants. A timeout would kill legitimate discussions.

**Failure mode**: If a participant crashes or the watcher is
stopped mid-discussion, the discussion stays `active` forever.
There's no dead-man switch.

**Mitigation**: None currently. This is a known gap.

---

## Summary

| # | Choice | Impact | Fixed |
|---|--------|--------|-------|
| 1 | Auto-actions without cooldown | Cascading loops | Partially |
| 2 | Retry as default | Amplifies all other bugs | Partially |
| 3 | Ephemeral failed_reason | Lost diagnostics | Partially |
| 4 | SQLite as passive sink | Concurrent watcher races | No |
| 5 | Status as string | Silent typos, 480 failure points | No |
| 6 | Subprocess as interface | Unhandled signal deaths | No |
| 7 | No budget/governor | Infinite work generation | No |
| 8 | No stale discussion timeout | Orphaned discussions | No |

"Partially" means v1.54 added mitigations but the underlying pattern remains.
