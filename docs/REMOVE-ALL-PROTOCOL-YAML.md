# Remove All Protocol YAML Files

Status: plan
Date: 2026-05-07
Depends on: REMOVE-CONTRACT-YAML.md (completed)

## Target

Remove these 4 YAML files as live dependencies. Each has a SQLite equivalent.
Only contract.yaml is safe to remove today. The other three need migration.

```
contract.yaml   →  SQLite tasks table        [DONE - Phase A-D complete]
inbox.yaml      →  SQLite inbox table         [TODO]
failures.yaml   →  SQLite failures table      [TODO]
decisions.yaml  →  SQLite decisions table     [TODO]
```

---

## inbox.yaml Migration

### Writes to fix (9 sites)

| # | Site | What |
|---|------|------|
| I1 | `inbox_watch.py:679` | `yaml.dump(inbox_items)` — GC/reconcile writes |
| I2 | `auto_schedule.py:143` | `yaml.dump(inbox)` — auto-enqueue |
| I3 | `archive_yaml.py:152` | `yaml.dump(inbox_rows)` — export |
| I4 | `discuss.py:264,281` | `_atomic_write(inbox_file, yaml.dump(...))` — approval |
| I5 | `yaml_io.py:51` | `yaml.dump(inbox_rows)` — generic YAML io |
| I6 | `onboard.py:392` | `inbox.write_text(yaml.dump(...))` — onboarding |
| I7 | `task.py:483` | `_write_items` via `engine/inbox.py` |
| I8 | `state_writer.py:340` | SQLite sync comment — already exists, check completeness |

### Reads to fix (~25 files)

Most already route through `state_reader.get_inbox_items()` which checks SQLite first. Key offenders:

| # | Site | What |
|---|------|------|
| I9 | `inbox_watch.py` — `_load_tasks` pattern | Switch inbox reads to inbox_dao |
| I10 | `inbox_dispatch.py` | Reads inbox for dispatch queue |
| I11 | `inbox_enqueue.py` | Reads inbox for duplicate check |
| I12 | `dashboard-ui.py` | Reads inbox for UI display |
| I13 | `auto_dispatch.py` | Reads inbox for status |
| I14 | `session-stop.sh` | Pauses inbox items on session end |

### Approach

Same pattern as contract.yaml:
1. Route all writes through `inbox_dao` (upsert/update)
2. Route all reads through `state_reader.get_inbox_items()` (SQLite path)
3. Remove YAML write fallback
4. Update agent hooks

---

## failures.yaml Migration

### Writes to fix

Failures are written via the `verify` command and the `failure_classifier`.
The `failures_dao` already exists. The YAML path is a sidecar write.

| # | Site | What |
|---|------|------|
| F1 | `validate.py` | Writes failures to YAML during repair |
| F2 | `failure_classifier.py` | Classifies and records failures — check write path |
| F3 | `verify.py` | Records verification failures |

### Reads to fix (12 files)

| # | Site | What |
|---|------|------|
| F4 | `context.py` | Reads failures for task context display |
| F5 | `preflight.py` | Checks past failures before dispatch |
| F6 | `doctor.py` | Health check reads failures |
| F7 | `adapter_payload.py` | Includes failures in payload |
| F8 | `onboard.py` | Reads failures during setup |

### Approach

Same pattern:
1. Route writes through `failures_dao`
2. Route reads through `state_reader.get_failures()`
3. Remove YAML path

---

## decisions.yaml Migration

### Writes to fix

Decisions are logged by agents during handoff. The `decisions_dao` already exists.

| # | Site | What |
|---|------|------|
| D1 | `handoff_write.py` | Writes decisions during handoff creation |
| D2 | `discuss.py` | Writes consensus decisions |

### Reads to fix (11 files)

| # | Site | What |
|---|------|------|
| D3 | `context.py` | Reads decisions for task context |
| D4 | `doctor.py` | Health check reads decisions |
| D5 | `adapter_payload.py` | Includes decisions in payload |

### Approach

Same pattern as failures.

---

## Implementation Order

```
Iteration 1: inbox.yaml writes  (I1-I8)   — 8 sites, most mechanical
Iteration 2: inbox.yaml reads   (I9-I14)  — 6 key sites + cleanup
Iteration 3: failures.yaml      (F1-F8)   — smaller scope, 8 sites
Iteration 4: decisions.yaml     (D1-D5)   — smallest scope, 5 sites
Iteration 5: Remove YAML tombstone files   — contract.yaml, inbox.yaml, failures.yaml, decisions.yaml
```

Each iteration follows the contract.yaml pattern:
1. Write a test that catches YAML/SQLite desync
2. Route the write/read through the DAO/state_reader
3. Verify test passes
4. Move to next site

## Risk

- **inbox.yaml** is the most heavily used. Breaking inbox dispatch breaks
  the entire auto-mode pipeline. This is the highest-risk migration.
- **failures.yaml** and **decisions.yaml** are lighter-weight — mostly read
  for display purposes. Lower risk.
- **session-stop.sh** still references inbox.yaml — needs to be updated
  to use `shux` CLI or DAO directly.
