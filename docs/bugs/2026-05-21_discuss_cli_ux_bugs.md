# Superharness `shux discuss` — UX and retry-alert bugs (v1.62.20)

**Reporter:** maintainer  
**Date:** 2026-05-21  
**Version:** v1.62.20  
**Environment:** macOS Darwin 25.5.0, Python 3.11.6 (editable install), pipx 1.7.0  
**Repro:** live session — `shux discuss start --topic "review https://github.com/vercel-labs/opensrc"`  

---

## 1. Verdict table

| # | Bug | Severity | Status |
|---|-----|----------|--------|
| I | `shux discussion` not recognized — `discuss` alias missing | Low / UX | ❌ Open |
| J | `shux discuss status <disc_id>` rejects positional arg — requires undocumented `--task` flag | Medium / UX | ❌ Open |
| K | Retry-alert fires on cancelled/stopped discussion shadow inbox items — false positive that never clears | Medium / Noise | ❌ Open |

---

## 2. Bugs

### Bug I — `shux discussion` command not found

**Symptom**

```
$ shux discussion "review https://..."
Error: No such command 'discussion'. Did you mean 'discuss'?
```

**Root cause**

`cli.py:138` registers only `discuss`. The natural plural form `discussion` is not registered as an alias. Click's "did you mean?" hint surfaces it but requires the user to know the difference.

**Repro**

```bash
shux discussion start --topic "anything"
```

**Fix**

Add alias in `cli.py` after the existing `discuss` registration:

```python
_cmd("discuss",     "Approval-gated consensus helpers.", module="superharness.commands.discuss")
_cmd("discussion",  "Alias for 'discuss'.",              module="superharness.commands.discuss")
```

**File:** `src/superharness/cli.py:138`

---

### Bug J — `shux discuss status <disc_id>` rejects positional argument

**Symptom**

```
$ shux discuss status discuss-20260521T191229Z-98866-424964093
discuss: error: unrecognized arguments: discuss-20260521T191229Z-98866-424964093
```

The natural invocation pattern `shux discuss status <id>` is rejected. The `status` subparser only accepts `--project` and `--task`; there is no positional slot for a discussion ID. Filtering to a specific discussion requires `--task`, which is a task ID filter (different semantic), not a discussion ID filter.

**Root cause**

`discuss.py:471-473` — the `status` argparse subparser defines no positional argument:

```python
p = sub.add_parser("status", add_help=True)
p.add_argument("--project", "-p", default=None)
p.add_argument("--task", default=None)
```

The `status` subcommand calls `cmd_status(handoff_dir, task_id=...)` which passes its filter as `task_filter` to the engine. There is no path to filter by discussion ID.

**Repro**

```bash
shux discuss status discuss-20260521T191229Z-98866-424964093
```

**Fix**

Add an optional positional `disc_id` argument to the `status` subparser; pass it through as the filter when provided:

```python
p = sub.add_parser("status", add_help=True)
p.add_argument("disc_id", nargs="?", default=None,
               help="Optional discussion ID to filter output")
p.add_argument("--project", "-p", default=None)
p.add_argument("--task", default=None)
```

And in the dispatch block:

```python
if opts.subcmd == "status":
    filter_id = getattr(opts, "disc_id", None) or getattr(opts, "task", None)
    rc = cmd_status(handoff_dir, task_id=filter_id)
```

**File:** `src/superharness/commands/discuss.py:471-473` and dispatch at `:549-550`

---

### Bug K — Retry-alert fires on cancelled discussion shadow inbox items

**Symptom**

`shux status` reports `retry-alert: threshold=3 high=4` pointing to 4 inbox items from two
cancelled discussions from 2026-05-11 (~10 days old). These items are `stopped` status, belong
to cancelled discussions, and will never be dispatched again. The alert never clears on its own.

```
retry-alert: threshold=3 high=4
  ids=20260511T120128Z-discuss-20260511T105450Z-...-r1-claude-code-...,
      20260511T120129Z-discuss-20260511T105450Z-...-r1-gemini-cli-...,
      ...
```

**Root cause**

`status.py:880-893` — the retry-alert scan checks all items in `active_statuses = {"pending", "launched", "running", "stale", "failed", "paused", "stopped"}` and flags any with `retry_count >= threshold`. It does not exclude items with `type="discussion"`.

Discussion shadow rows are created in `discuss.py:_enqueue_sqlite_shadow` with `max_retries=1`. However, the auto-recover logic in `inbox_watch.py:1706-1713` increments `max_retries` by 1 on each recovery attempt (`max_retries = max_retries + 1`). After two recoveries, `max_retries` reaches 3 and `retry_count` catches up. Once the parent discussion is cancelled (but not properly drained via `shux discuss close`), the shadow rows remain in `stopped` status with elevated `retry_count` permanently triggering the alert.

The `stopped` status is intentionally in `active_statuses` for regular task items (a stopped task may need operator attention). But for discussion shadow rows it is terminal — the discussion is over. They should never contribute to the retry-alert signal.

**Repro**

1. Start a discussion, let agents fail or cancel it without calling `shux discuss close`
2. Wait for auto-recover to bump `max_retries` 2+ times on the shadow rows
3. Run `shux status` — retry-alert fires and never clears

**Fix**

In `status.py` retry-alert scan, skip items where `item.get("type") == "discussion"`. Discussion items have their own health signal in the `discussions:` line of `shux status` and do not belong in the generic retry-alert:

```python
for item in inbox_health["items"]:
    if item.get("type") == "discussion":
        continue  # discussion shadow rows have their own health signal
    st = str(item.get("status", ""))
    ...
```

**File:** `src/superharness/commands/status.py:882` (inside retry-high loop)

---

## 3. Operational fallout

All three bugs fire together in any session that uses `shux discuss`:

1. User types `shux discussion` → hard error, must know to use `discuss` instead
2. User tries `shux discuss status <id>` to check progress → hard error, must use `shux discuss list` as workaround
3. After any cancelled discussion, `shux status` shows a permanent retry-alert with high=N that cannot be cleared without manually running `shux status --fix` or directly updating the SQLite inbox rows

## 4. Minimum patch

- `cli.py:138`: add `discussion` alias (1 line)
- `discuss.py:471-473`: add `disc_id` positional to `status` subparser + update dispatch
- `status.py:882`: skip `type="discussion"` items in retry-alert loop (1 line)
