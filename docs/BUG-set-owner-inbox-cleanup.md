# BUG: `task set-owner` — ImportError silently breaks inbox cleanup

**Filed:** 2026-05-09
**Version observed:** superharness 1.54.3
**Severity:** medium (operation reports success; orphan inbox items accumulate)
**Affected command:** `shux task set-owner` on any task with active inbox items
**Status:** open

---

## Symptom

```
$ shux task set-owner --id <task-id> --owner <new-owner>
...
ImportError: cannot import name '_load_items' from 'superharness.engine.inbox'
Reassigned task '<task-id>': <old-owner> → <new-owner>
```

The "Reassigned" line still prints. The cleanup block that should follow it is silently skipped because of the ImportError. The user sees a green-looking confirmation; the inbox is left dirty.

## Root cause

`superharness/commands/task.py:483`:

```python
from superharness.engine.inbox import _inbox_lock, _load_items, _write_items
```

`superharness/engine/inbox.py` does not define `_load_items` or `_write_items`. The module exports:

```
_inbox_lock, enqueue, set_field, normalize,
_process_alive, _deps_satisfied, _task_is_dispatch_ready
```

Looks like a refactor moved or renamed those two helpers without updating the import site in `commands/task.py`.

## Functional impact

The block guarded by this import (`commands/task.py:482-510`) is supposed to:

1. Acquire the inbox lock (`_inbox_lock`)
2. Load all inbox items (`_load_items`)
3. For items dispatched to the OLD owner, SIGTERM their PIDs and drop them
4. Write the kept items back (`_write_items`)

When the import fails, none of that runs. Result: reassigning ownership away from an agent that has pending/launched/running inbox items leaves those items orphaned. They still reference the old owner. Watcher behaviour beyond that point is undefined.

Lines that depend on the missing names:

```python
# task.py:483
from superharness.engine.inbox import _inbox_lock, _load_items, _write_items

# task.py:488-489
with _inbox_lock(inbox_file):
    items = _load_items(inbox_file)

# task.py:507
_write_items(inbox_file, keep)
```

## Reproduction

1. Create a task with one of the agent owners (e.g. `claude-code`).
2. Cause an inbox item to be dispatched to that owner (`shux delegate <task-id>` or any auto-dispatch path).
3. Reassign: `shux task set-owner --id <task-id> --owner codex-cli`.
4. Observe: the ImportError is printed, the reassignment is confirmed, but the inbox still contains the original `claude-code` item.

## Fix options

**A — Restore the missing exports in `engine/inbox.py`.** If `_load_items` and `_write_items` were intentionally inlined elsewhere or renamed, re-export them under their old names so callers keep working.

**B — Update the import site in `commands/task.py:483`** to call whatever the new helpers are, and update lines 489 and 507 accordingly. This is probably the right fix if the rename was deliberate.

Either way, the failure mode is bad enough to warrant an integration test: `set-owner` with at least one active inbox item present should leave a clean inbox afterwards.

## Secondary concern: silent failure

The ImportError is being caught and printed but does not abort the command. That makes this look cosmetic when it is actually breaking inbox state. Worth auditing the surrounding error handling in `commands/task.py` so import failures in cleanup blocks at least surface as warnings, ideally as exit-non-zero.

## Observed during

semblar session 2026-05-09, while reassigning `learnings-digest` task ownership from `owner` to `claude-code`. No active inbox items existed in our case so the functional impact was zero, but the silent-failure pattern is the real concern.

## References

- `superharness/commands/task.py:483-510` — the affected code path
- `superharness/engine/inbox.py` — module the import targets
- Detected in pipx install at `~/.local/pipx/venvs/superharness/lib/python3.14/site-packages/superharness/`
