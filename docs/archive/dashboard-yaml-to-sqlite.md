# Plan: Dashboard YAML reads → SQLite via state_reader

**Status:** plan_proposed
**Owner:** claude-code
**Repo:** superharness
**Target version:** 1.44.16 (patch)
**Method:** TDD (RED → GREEN → REFACTOR)

---

## Context

`scripts/dashboard-ui.py` has 25 `yaml.safe_load()` calls. 14 of them read contract.yaml or inbox.yaml — both **tombstones** since v1.43. In `sqlite_only` mode (default), superharness writes all state to `state.sqlite3` and stops updating those YAML files. As a result, the dashboard shows stale data that drifts from the canonical SQLite state.

The remaining 11 reads are legitimate — handoffs, discussions, and agent-pulse files are stored as YAML by design.

## Scope

### In (4 steps)

| Step | What | Lines |
|---|---|---|
| 1 | Add `get_failures()`, `get_decisions()`, `get_ledger_entries()` to `state_reader.py` | ~40 new |
| 2 | Delete dead YAML fallback branches (8 contract reads with `else: yaml.safe_load()`) | ~20 removed |
| 3 | Migrate 1 inbox YAML read to `state_reader.get_inbox_items()` | ~10 changed |
| 4 | Fix 5 read-modify-write paths (read contract.yaml, mutate, write YAML → SQLite read+write) | ~80 changed |

### Out
- Discussion subsystem (separate concern)
- Handoff YAML reads (legitimate, not tombstones)
- agent-pulse/status YAML files (legitimate)
- Removing `import yaml` from dashboard-ui.py (still needed for handoff/discussion YAML)
- Deleting tombstone YAML files from disk (blocked until ALL consumers migrated)

---

## Step 1 — Add missing state_reader functions

**File:** `src/superharness/engine/state_reader.py`

Three new functions that read from SQLite tables the dashboard needs:

### `get_failures(project_dir: str) -> list[dict]`
Read from SQLite `failures` table. Returns list of failure dicts with fields: task_id, severity, error_snippet, error_type, agent, date.

```python
def get_failures(project_dir: str) -> list[dict]:
    from dataclasses import asdict
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import failures_dao
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = failures_dao.get_all(conn)
        return [asdict(r) for r in rows]
    finally:
        conn.close()
```

### `get_decisions(project_dir: str) -> list[dict]`
Read from SQLite `decisions` table. Returns list of decision dicts.

### `get_ledger_entries(project_dir: str, *, hours: int | None = None) -> list[dict]`
Read from SQLite `ledger` table. Optional time window filter.

### RED tests
Add `tests/unit/dashboard/test_state_reader_coverage.py`:
- `test_get_failures_returns_empty_list_for_empty_db`
- `test_get_failures_returns_seeded_rows`
- Same pattern for decisions and ledger

---

## Step 2 — Delete dead YAML fallback branches

**File:** `src/superharness/scripts/dashboard-ui.py`

Since `_get_backend()` always returns `sqlite_only` (line 23 of state_reader.py), the YAML fallback branches are dead code. Remove them from these functions:

| Line | Function | Action |
|---|---|---|
| 838 | `contract_owners` | Delete `except: yaml.safe_load` branch |
| 1041 | `contract_id` | Replace YAML read with `state_reader.get_contract_doc().get("id")` |
| 1066 | `contract_tasks` | Delete `if not raw_tasks: yaml.safe_load` fallback |
| 1152 | `pending_approvals` | Delete `if all_tasks is None: yaml.safe_load` branch |
| 1443 | `_get_handoff_data` (contract fallback) | Delete YAML fallback |
| 1550 | Contract read for status display | Replace with state_reader |
| 1602 | Contract read for health check | Replace with state_reader |
| 1936 | `_handle_action` task delete | Already removes from SQLite first; keep YAML write for dual-mode compat |
| 1961 | `_handle_action` set_owner | Needs SQLite write path |

### RED tests
Add `tests/unit/dashboard/test_dashboard_sqlite_only.py`:
- `test_dashboard_renders_without_tombstones` — dashboard works without contract.yaml
- `test_dashboard_ignores_stale_yaml` — SQLite data wins
- `test_no_yaml_safe_load_for_contract_inbox` — static regex check

---

## Step 3 — Migrate inbox reads

**File:** `src/superharness/scripts/dashboard-ui.py`

| Line | Current | Replacement |
|---|---|---|
| 301 | `yaml.safe_load(inbox_file_content)` | `state_reader.get_inbox_items(project_dir)` |

The `inbox_counts` function reads `inbox.yaml` to count items by status. Replace with `state_reader.get_inbox_items()` which already exists.

---

## Step 4 — Fix read-modify-write paths

**File:** `src/superharness/scripts/dashboard-ui.py`

Five functions that read contract.yaml, mutate a task field, then write the entire contract back to YAML. In sqlite_only mode, the YAML write is a no-op (contract.yaml is not the source of truth). These must be rewritten to use SQLite for both read and write.

| Line | Function | Mutation | Fix |
|---|---|---|---|
| 1219 | `_set_task_status` | Set task status | Read from `tasks_dao.get()`, write via `tasks_dao.update()` |
| 1261 | Status change (variant) | Set task status | Same pattern |
| 1316 | Status display update | Set task field | Same pattern |
| 1936 | `_handle_action` task delete | Delete task | Use `conn.execute("DELETE FROM tasks WHERE id = ?")` |
| 1961 | `_handle_action` set_owner | Change owner | Use `tasks_dao.update(conn, task_id, changes={"owner": new_owner})` |
| 2870 | Owner removal (bulk) | Remove tasks by owner | Use `conn.execute("DELETE FROM tasks WHERE owner = ?")` |

Pattern for each:
```python
# Before
doc = yaml.safe_load(contract_file.read_text())
for t in doc["tasks"]:
    if t["id"] == task_id:
        t["status"] = "done"
contract_file.write_text(yaml.dump(doc))

# After
from superharness.engine.db import get_connection
from superharness.engine import tasks_dao
conn = get_connection(project_dir)
tasks_dao.update(conn, task_id, changes={"status": "done"})
conn.commit()
conn.close()
```

---

## Verification (end-to-end)

```bash
# 1. Unit tests
cd ~/DevOpsSec/superharness
python -m pytest tests/unit/dashboard/ -v

# 2. Manual: dashboard renders without tombstone files
mv .superharness/contract.yaml .superharness/contract.yaml.bak
shux dashboard   # should still work, showing tasks from SQLite
mv .superharness/contract.yaml.bak .superharness/contract.yaml

# 3. Static check: zero yaml.safe_load for contract/inbox
rg "yaml.safe_load.*contract|yaml.safe_load.*inbox" src/superharness/scripts/dashboard-ui.py
# Should return 0 matches

# 4. Dashboard diff test
# Render before and after, diff the HTML output — should be identical
# except for "stale YAML" warnings disappearing
```

---

## Release

- Bump `pyproject.toml`: `1.44.15` → `1.44.16` (patch)
- CHANGELOG entry
- PR → merge → tag → GitHub release

---

## Dependencies

- Requires `superharness>=1.44.15` (adapter-payload fix already landed)
- Requires SQLite tables `failures`, `decisions`, `ledger` to exist (added in v1.43 migration)

---

## Done: owner_label normalization (v1.44.16 pre-work)

Already committed in `adapter_payload.py`:

- Added `_OWNER_DISPLAY` mapping: `"owner"` → `"@you"` (other known agents pass through)
- Added `_owner_label()` helper
- Emit `"owner_label"` on every task and subtask entry in the payload

Morpheme side:
- `adapter.js` passes `teamLabel` through from `owner_label`
- `LeafNode.vue` and `SubtaskNode.vue` display `teamLabel || team` in the owner pill

This fixes the `owner: owner` redundancy without changing the canonical owner value.
