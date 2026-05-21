# Investigation: why `ai_driven` autonomy did not dispatch (morpheme project)

**Filed:** 2026-05-21
**Version observed:** superharness 1.62.7 (daemon last ran on the version installed ~May 2)
**Severity:** high — `ai_driven` projects silently stop dispatching; enqueue crashes fatally
**Affected:** autonomy daemon (`shux daemon` / `shux operator`), `engine/inbox.py` enqueue path, `shux discuss start`
**Status:** open
**Project investigated:** `/Users/airm2max/DevOpsSec/morpheme` (`autonomy: ai_driven`, `require_tdd: true`)
**Related:** `bugs/2026-05-11_discuss_dispatch_bugs.md` (Bug G — runaway round-1 re-dispatch), `BUG-set-owner-inbox-cleanup.md` (same class: refactor moved a helper, import site not updated)

---

## Verdict

`ai_driven` autonomy is **not ambient**. It only drives tasks while (a) a per-project dispatcher process is alive **and** (b) the enqueue path is healthy. For the morpheme project both were broken, in three layers:

| Layer | Cause | Effect |
|-------|-------|--------|
| 1 — runtime | No autonomy daemon running for the project (died ~May 2, never restarted) | Nothing consumes the inbox; tasks sit forever |
| 2 — code (1.62.7) | `engine/inbox.py` enqueue crashes: wrong import + undefined `logger` in the except handler | Even if the daemon is restarted, every enqueue dies |
| 3 — historical | When the daemon *did* run, it looped re-queuing discussion round-1 without converging | 4 discussions "active" for ~21 days, 47 dead round logs |

The operator's mental model is the trap: a running **dashboard** and a running **UI poller** both *observe* state. The **dispatcher** (daemon) is a separate process — and it had been dead for 19 days.

---

## Symptom

1. `shux status` reports the watcher `level=bad not loaded, heartbeat stale (last heartbeat ~29,815m ago)` and 11 issues (orphaned/stale/dead-PID inbox items, 4 discussions active ~504h).
2. `shux discuss start` creates the discussion record but crashes during inbox dispatch:

```
ImportError: cannot import name '_ensure_task_in_sqlite' from 'superharness.commands.inbox_enqueue'

During handling of the above exception, another exception occurred:

  File ".../superharness/engine/inbox.py", line 242, in enqueue
    logger.warning("inbox.py unexpected error: %s", e, exc_info=True)
NameError: name 'logger' is not defined
```

3. New tasks (including the just-created discussion round) stay `in_progress`/pending and never dispatch.

---

## Root cause

### Layer 1 — the dispatcher process is dead

- `shux daemon status` → `daemon: stopped (pid stale)`, pid `20079` (confirmed **dead** via `ps -p 20079`).
- `.superharness/launcher-logs/daemon.out.log` last write **2026-05-02 16:48** — ~19 days before investigation. The daemon died and was never restarted.
- The only autonomy process on the machine is `shux operator start --port 8787` (pid `80814`) bound to a **different project** (`open-generative-ai`). Daemons/operators are per-project; this one does nothing for morpheme.
- The morpheme process that *is* alive (pid `86762`) is the **UI's read-only adapter-payload poller** (a `/bin/sh` loop running `shux adapter-payload --json` every 2.5s into a tmp cache). It feeds the dashboard; it **never dispatches**.

**Consequence:** with no dispatcher, the inbox accumulates (6 pending / 4 launched / 0 running at investigation time) and `ai_driven` drives nothing.

### Layer 2 — `engine/inbox.py` enqueue crash (new in 1.62.x)

Two defects compound in the FK-guard block of `enqueue()`:

```python
# superharness/engine/inbox.py  (~line 238)
try:
    from superharness.commands.inbox_enqueue import _ensure_task_in_sqlite   # 239  ← wrong module
    _ensure_task_in_sqlite(conn, task, project_dir, created_at)              # 240
except Exception as e:
    logger.warning("inbox.py unexpected error: %s", e, exc_info=True)        # 242  ← undefined name
    pass
```

1. **Stale import path** (`inbox.py:239`). `_ensure_task_in_sqlite` is **not** in `commands/inbox_enqueue.py`. It is defined in `commands/inbox_watch.py:55` (and called there at `:74`, `:2137`, `:2284`). A refactor relocated the helper without updating this import site → `ImportError`. Same failure class as `BUG-set-owner-inbox-cleanup.md`.

2. **Undefined `logger` in the handler** (`inbox.py:242`). The module defines `_log = logging.getLogger(__name__)` at line 27 — there is no `logger`. The `except` was clearly *intended* to swallow the ImportError (note the trailing `pass`) and degrade gracefully, but referencing `logger` raises `NameError`, converting a recoverable warning into a **fatal crash** of `enqueue()`.

**Consequence:** any enqueue that reaches the FK-guard block dies. That includes discussion-round dispatch and auto-dispatch of newly classified tasks — so the daemon cannot make progress even if restarted.

### Layer 3 — historical non-convergence (already known: Bug G)

`daemon.out.log` (through May 2) shows the daemon never converged on the 4 pre-existing discussions:

```
auto-retry (sqlite): re-queued 'discuss-…/round-1' (attempt 1/3)      ← repeated endlessly
log-analyzer: 'discuss-…/round-1' active (files changing, 1517m elapsed)
result=ok exceeded=0 (no launched items)
```

This is **Bug G** from `bugs/2026-05-11_discuss_dispatch_bugs.md` (runaway round-1 re-dispatch): agents were launched (47 `discuss-*_round-1-*.log` files in `launcher-logs/`) but never reached a terminal state, so the daemon re-queued them indefinitely. `daemon.err.log` also shows the deadline-check helper crashing on an empty temp file (`JSONDecodeError: Expecting value: line 1 column 1` reading `superharness-deadline-*`).

---

## Timeline

| When | Event |
|------|-------|
| until ~2026-05-02 | morpheme daemon running (older version), looping on discussions (Bug G), never converging |
| ~2026-05-02 16:48 | daemon stops (pid 20079); never restarted |
| ~2026-05-20 | superharness upgraded to 1.62.6/1.62.7 — `inbox.py` enqueue bug now present |
| 2026-05-21 | `shux discuss start` → enqueue crash (Layer 2); daemon still down (Layer 1) → round-1 task stuck `in_progress` |

---

## Fix

### Patch set (minimal)

`engine/inbox.py`:

```python
# 239: point at the module that actually defines the helper
from superharness.commands.inbox_watch import _ensure_task_in_sqlite

# 242: use the module logger that exists
_log.warning("inbox.py unexpected error: %s", e, exc_info=True)
```

Notes:
- Fixing **only** `logger`→`_log` restores enqueue but *skips* the FK guard (the ImportError is swallowed) — acceptable for migrated projects, but loses the "FOREIGN KEY constraint failed" protection the guard was added for.
- Fixing **both** lines restores the intended behavior: the FK guard runs, and any genuine failure degrades to a logged warning instead of crashing.
- Add a regression test: `enqueue()` against a project whose task exists only in `contract.yaml` (pre-SQLite) must not raise, and must insert the inbox row. Guard against the import path with a test that imports `_ensure_task_in_sqlite` from `commands.inbox_watch` and asserts `inbox.py` references the same symbol.

### Operational recovery (morpheme)

1. Apply the `inbox.py` patch, reinstall (`pipx upgrade superharness` from the fixed source).
2. `shux status --fix` — GC dead-PID/orphan inbox items, close the 4 stale Apr-30 discussions.
3. `shux daemon start` — restart the per-project dispatcher (only effective after step 1).
4. Confirm: `shux daemon status` shows a live pid + fresh heartbeat; `shux status` watcher `level` clears.

### Hardening (prevent recurrence)

- **Import-site guard:** a CI check / test that asserts cross-module private imports (`_ensure_*`, `_load_*`, `_write_*`) resolve — this class of bug (`BUG-set-owner-inbox-cleanup.md`, this report) keeps recurring after refactors.
- **No bare `logger`:** lint rule or test that `engine/inbox.py` (and siblings) reference the defined `_log`, not `logger`.
- **Daemon liveness surfacing:** `shux status` already flags a stale heartbeat, but a dead dispatcher on an `ai_driven` project is silent until someone looks. Consider a louder signal (or auto-restart) when `autonomy=ai_driven` and the daemon pid is dead.

---

## Repro

```bash
# In any ai_driven project on superharness 1.62.7:
shux discuss start --owners claude-code,codex-cli --topic "x" --max-rounds 3
# → discussion record created, then:
#   ImportError: cannot import name '_ensure_task_in_sqlite' from 'superharness.commands.inbox_enqueue'
#   NameError: name 'logger' is not defined   (fatal)

# Daemon liveness:
shux daemon status        # → stopped (pid stale)
ps -p <pid_from_status>   # → dead
```

## Diagnostic artifacts (commands used in this investigation)

```bash
shux status
shux daemon status
shux workflow
ps aux | grep -iE "shux|superharness|operator|daemon"
tail .superharness/launcher-logs/daemon.{out,err}.log
grep -rn "_ensure_task_in_sqlite" <site-packages>/superharness
sed -n '230,250p' <site-packages>/superharness/engine/inbox.py
```
