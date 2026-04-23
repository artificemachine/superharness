# Watcher Instability — Session 2026-04-23 (IMPLEMENTED)

**Date:** 2026-04-23
**Version at handoff:** v1.30.2 (changes pending v1.30.3)
**Branch:** main
**Status:** Fix 1 implemented. Fix 2 already done. Fix 3 not applicable (see below).

---

## Context

The inbox watcher (`com.superharness.inbox.superharness` launchd job) is chronically
unstable: heartbeat goes stale, tasks get double-dispatched or permanently frozen,
and `failures.yaml` fills with noise that obscures real failures.

A full code review of `src/superharness/commands/inbox_watch.py` produced the root
cause list below. Three fixes were identified and are ready to implement.

---

## Root Causes (7 total)

1. **launchd single-cycle model** — The plist uses `StartInterval = 15`. No persistent
   process runs. If macOS throttles, suspends, or kills the job, ticks are simply
   missed. No retry, no backpressure. This is by design and not trivially fixable
   without switching to a daemon model, so it is low-priority.

2. **`auto_enqueue_approved` writes inbox without `_inbox_lock`** (`inbox_watch.py`
   lines 474-479). Every other inbox writer holds the file lock before writing.
   This one does not. Under concurrent cycles (launchd sometimes fires twice), the
   two writes race and corrupt the YAML. **Highest-impact fix.**

3. **Dispatch is fire-and-forget `Popen`** (line 218-219). The watcher launches the
   agent subprocess and moves on. On the next tick, if the PID has not appeared in
   the lock dir yet, the item can be dispatched again. Double-dispatch = wasted work
   and orphaned processes.

4. **Zombie reconciler marks clean exits as `failed`** — `_reconcile_zombies` checks
   `psutil.pid_exists(pid)`. Any PID that no longer exists is marked `failed`, even
   if the agent completed successfully and wrote its own status update. Agents that
   finish quickly get falsely failed and re-queued.

5. **`archived` is not treated as `done` in `_deps_satisfied`** (`engine/inbox.py`).
   When a task is archived (closed via `shux close`), its `blocked_by` dependents
   never unblock because `archived` is not in the done-equivalent set. Those
   dependents are permanently frozen.

6. **Lock dir + PID write are not atomic** — The watcher creates a lock directory
   then writes a PID file. If the process crashes between mkdir and write_pid, no
   future cycle can claim the lock (directory exists, no valid PID inside). The item
   stays `launched` forever. No recovery until the 30-min zombie timeout fires.

7. **Preflight WARNs written to `failures.yaml`** (`commands/delegate.py`) — Advisory
   warnings emitted during pre-dispatch validation (e.g., missing optional config)
   are recorded as failures. Real dispatch failures drown in noise; alert fatigue
   makes `failures.yaml` useless as a signal.

---

## Three Fixes to Implement (in order)

### Fix 1 — Add `_inbox_lock` to `auto_enqueue_approved`

**File:** `src/superharness/commands/inbox_watch.py`
**Location:** lines 474-479 (the block that writes inbox_items without a lock)

Find the `auto_enqueue_approved` function. It currently does:

```python
with open(inbox_file, "w", encoding="utf-8") as _f:
    _f.write(_yaml.dump(inbox_items, default_flow_style=False))
```

Replace with the same lock pattern used by `auto_enqueue_todo` (around line 361):

```python
from superharness.engine.inbox import _inbox_lock
with _inbox_lock(inbox_file):
    with open(inbox_file, "w", encoding="utf-8") as _f:
        _f.write("# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n")
        _yaml.dump(inbox_items, _f, default_flow_style=False, sort_keys=True)
```

Verify `_inbox_lock` is already imported at the top of inbox_watch.py before adding
a second import. If it is, remove the local import line.

### Fix 2 — Treat `archived` as `done` in `_deps_satisfied`

**File:** `src/superharness/engine/inbox.py`
**Function:** `_deps_satisfied`

Find the set of statuses that count as "done" for dependency checking. It currently
contains something like `{"done", "failed", "stale"}` or just `{"done"}`.
Add `"archived"` to that set so tasks blocked on an archived task can proceed.

### Fix 3 — Separate preflight WARNs from `failures.yaml`

**File:** `src/superharness/commands/delegate.py`
**Goal:** Preflight advisory warnings must NOT be written to `failures.yaml`.

Find all paths where a `WARN` or advisory message is written to `failures.yaml` during
preflight validation. Move those to stdout/log only. Only actual dispatch failures
(subprocess error, agent crash, timeout) should be recorded in `failures.yaml`.

---

## After Implementing

1. Run full unit suite:
   ```bash
   PYTHONPATH=src ~/.pyenv/versions/3.11.6/bin/python -m pytest tests/unit/ -q
   ```
   Expected: same 11 pre-existing failures, nothing new.

2. Bump version in `pyproject.toml` to `1.30.3`.

3. Append CHANGELOG.md entry.

4. Create PR, merge, verify CI tags and publishes to PyPI.

5. Reload the watcher:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.superharness.inbox.superharness.plist
   launchctl load  ~/Library/LaunchAgents/com.superharness.inbox.superharness.plist
   launchctl kickstart -k gui/$(id -u)/com.superharness.inbox.superharness
   ```

---

## Known Pre-Existing Test Failures (not caused by this session)

- 9 failures in `tests/unit/test_session_stop.py` — `session-stop.sh` calls bare
  `python3` which resolves to homebrew 3.14 (no `yaml` installed). Fix: inject
  `SUPERHARNESS_PYTHON` or `PYTHONPATH` into that script's python3 calls.
- 1 failure in `tests/unit/test_delegate_logic.py::test_delegate_sdk_logic_claude_vs_others`
  — pre-existing, not investigated.

---

## Test Command Reference

```bash
# Run full unit suite (correct Python + src in path)
PYTHONPATH=src ~/.pyenv/versions/3.11.6/bin/python -m pytest tests/unit/ -q

# Run single file
PYTHONPATH=src ~/.pyenv/versions/3.11.6/bin/python -m pytest \
  tests/unit/test_delegate.py -q

# Install current dev version (run from repo root)
pip install -e .

# Reload watcher after install
launchctl unload ~/Library/LaunchAgents/com.superharness.inbox.superharness.plist
launchctl load   ~/Library/LaunchAgents/com.superharness.inbox.superharness.plist
```
