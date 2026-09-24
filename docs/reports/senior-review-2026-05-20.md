# Senior Review — superharness

**Date:** 2026-05-20
**Branch:** `main`, commit `488c8d7`
**Scope:** `src/superharness/` (~120 Python files)
**Verdict:** **REJECTED**

---

## 🔴 Critical (Must Fix)

### C1. Duplicate `_migration_v5` — migration overwrites itself
**File:** `engine/db.py`, lines 399-406

Two identical `_migration_v5` definitions. The second silently overwrites the first in `_MIGRATIONS`. Copy-paste error that could mask a lost migration. Delete the duplicate.

### C2. Duplicate `"todo"` key in `_MAPPING` — state machine ambiguity
**File:** `engine/next_action.py`, lines 52 and 72

The `"todo"` key appears twice with different `legal` lists:
- Line 52: `["plan_proposed"]`
- Line 72: `["plan_proposed", "waiting_input"]`

The second overwrites the first. If `waiting_input` is intentional, the first entry is dead code. If accidental, the state machine has an unintended transition. Resolve which is correct.

### C3. 392 bare `except Exception:` blocks — widespread error suppression
**Files:** 100+ locations. Worst offenders:
- `inbox_watch.py`: 68+ instances
- `dashboard-ui.py`: 25+ instances
- `state_writer.py`: multiple silent catches
- `cli.py`: 9 registration functions with `except Exception: pass`

The watcher (most critical runtime component) can degrade to doing nothing with zero diagnostics. Every bare `except Exception:` must log at WARNING+ or be scoped to a specific exception type.

### C4. `cli.py` is 1,021 lines — not a "thin entry point"
Claims to be thin. Contains: CLI routing, process management, network I/O, package management, thread management, backward-compat aliases. At least 6 responsibilities. Extract into dedicated modules.

### C5. `delegate.py` is 1,446 lines — god module
Single command file handling: prompt construction, context hints, CLI dispatch, SDK dispatch, model routing, budget estimation, worktree setup, env snapshots, dispatch profiles, parallel dispatch, JSON output. Should be ~200 lines. Decompose into `dispatcher.py`, `prompt_builder.py`, `context_hint.py`.

### C6. `dashboard-ui.py` is 3,426 lines — monolith, no test coverage
3.4k-line HTTP server with inline HTML, mutable global state, zero tests. Extract handlers, dashboard logic, and templating.

---

## 🟡 Major (Should Fix)

### M1. Model shortcuts hardcoded at module level
**File:** `cli.py:24-30` — `MODEL_SHORTCUTS` dict. Model IDs change; should come from config, not a code constant requiring a release to update.

### M2. `_run_dashboard` is 100+ line procedural monolith
**File:** `cli.py:436-540` — checks, kills, launches, polls, writes state. Split into `_launch_dashboard`, `_check_running`, `_kill_stale`, `_wait_for_url`, `_write_operator_state`.

### M3. `ConfigDict(extra="allow")` on every Pydantic model
**File:** `engine/schemas.py` — every model allows unknown fields silently, defeating schema validation. Restrict to models that genuinely need extensibility.

### M4. Database connection management is repeated 50+ times
Every function opens connection → init_db → work → commit → close. Create a `@contextmanager` that handles the full lifecycle.

### M5. `_ACTIVE_WORK_STATES` defined twice in `state_writer.py`
Lines 32 and 159. Identical frozensets. DRY violation.

### M6. `_row_to_task` has 30+ `"key" in keys` defensive checks
**File:** `tasks_dao.py:310-366` — masks migration bugs. Missing columns should raise loudly, not silently return None.

### M7. JSON deserialization at read time has no error handling
**File:** `tasks_dao.py:328` — `json.loads(row["acceptance_criteria"])` crashes on malformed JSON. Wrap with try/except and safe default.

### M8. `_backup_db` silently swallows exceptions, migration proceeds
**File:** `db.py:31-47` — if backup fails (disk full, perms), migration runs anyway. Should abort.

### M9. Direct string interpolation into SQL
**File:** `tasks_dao.py:192` — `f"... IN ({placeholders})"` is fragile. Use parameterized approach consistently.

### M10. `_ensure_active_inbox` swallows all errors
**File:** `state_writer.py:60-61` — if inbox creation fails, task moves to `in_progress` with no inbox item, watcher never dispatches, nothing logged.

### M11. `cmd_help` command is redundant
**File:** `cli.py:894-898` — Click already handles `--help`. Adds nothing.

---

## 🟠 Minor

- `cli.py`: `import click as _click` inside functions that already have `click` at module level (lines 191, 281, 299)
- `contract_io.py:114-121`: nested ternary for `blocked_by` parsing is unreadable
- `ts_map` dict in `state_writer.py:122` defined inline — extract to module constant

---

## 📐 Architecture Notes

### A1. Error suppression is systemic — needs architecture-level fix
The codebase treats exception handling as "catch everything, move on" rather than "fail fast, diagnose, recover." Add linting rule banning bare `except Exception:`, retrofit top 10 silent catches first.

### A2. State machine lives in 4+ places
`next_action.py` (`_MAPPING` + `STATUS_TO_COL`/`STATUS_GROUPS`), `schemas.py` (`TaskStatus`), and various commands. Adding a status requires updates in all of them. Derive from the enum, not parallel lists.

### A3. YAML → SQLite migration is incomplete
Dead/deprecated paths still exist: `_export_contract_yaml`, `_export_inbox_yaml`, `parity.py`, `yaml_sync.py`. Remove them.

### A4. The watcher is too large to review effectively
`inbox_watch.py` appears to be 3,500+ lines. Handles dispatch, heartbeat, stale recovery, discussion auto-advance, retry, burst guarding. Most critical runtime component, unmaintainable at this size.

---

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 6 |
| 🟡 Major | 11 |
| 🟠 Minor | 4 |
| 📐 Architecture | 4 |

**Immediate actions:**
1. Fix C1 (delete duplicate `_migration_v5`)
2. Fix C2 (resolve duplicate `"todo"` key)
3. Begin C3 remediation on top 10 silent exception handlers

**Medium-term:** Decompose `inbox_watch.py`, `delegate.py`, `dashboard-ui.py`, and `cli.py`.
