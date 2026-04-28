# YAML → SQLite Migration: Completion Plan

**Status:** In progress (dual-mode: YAML + SQLite, parity checking active)
**Target:** SQLite is sole source of truth; YAML is on-demand export only

---

## Current State (v1.41.0)

All state writes go to both YAML and SQLite. All reads go to SQLite first, with YAML fallback.
A separate parity system detects drift and can heal in either direction.

This means every state mutation has **two code paths** to maintain:

```
Write path:  code → contract_io.write_contract() → YAML file + SQLite mirror
Read path:   code → state_reader.get_*() → SQLite (try) → YAML (fallback)
Drift fix:   watcher tick → parity.check_parity() → parity.heal_parity()
Sync queue:  yaml_sync.enqueue_op() → yaml_sync.drain() → YAML write
```

The dual-write infrastructure spans ~2,000 LOC across `parity.py`, `yaml_sync.py`, `state_writer.py`, and YAML fallback paths in every DAO and command module.

---

## Scope: What Changes

### Modules to rewrite (remove YAML writes)

| Module | Current behavior | Target behavior |
|--------|-----------------|-----------------|
| `contract_io.py` | Writes to contract.yaml, calls `_sync_to_sqlite()` | SQLite write only. Export to YAML is a separate command. |
| `state_writer.py` | `mirror_*()` writes both YAML and SQLite | Remove mirror functions. Inline SQLite writes in callers. |
| `lifecycle_rules.py` | `yaml.dump()` to inbox.yaml and contract.yaml | SQLite writes. No YAML. |
| `task.py` | `yaml.dump()` contract + inbox | SQLite writes only. |
| `close.py` | `yaml.dump()` contract | SQLite write only. |
| `inbox_dispatch.py` | `yaml.dump()` inbox | SQLite write only. |
| `inbox_watch.py` | Multiple `yaml.dump()` sites | SQLite writes only. |
| `inbox_enqueue.py` | `yaml.dump()` inbox | SQLite write only. |
| `review_escalation.py` | `yaml.dump()` contract | SQLite write only. |
| `dashboard-ui.py` | ~20 direct `yaml.dump()` write sites | SQLite writes via DAO modules. |

### Modules to rewrite (remove YAML reads)

| Module | Current behavior | Target behavior |
|--------|-----------------|-----------------|
| `state_reader.py` | `_from_yaml()` fallbacks on every read path | Remove all `_from_yaml()` methods. SQLite only. Remove `_get_backend()` |
| `dashboard-ui.py` | ~30 direct `yaml.safe_load()` read sites | All reads via `state_reader` or DAOs. |
| `inbox_watch.py` | Multiple `yaml.safe_load()` reads | All reads via DAOs. |
| `lifecycle_rules.py` | Direct `yaml.safe_load()` of inbox.yaml and contract.yaml | Read via `state_reader` or DAOs. |
| `task.py` | Direct contract.yaml reads | Read via DAOs. |
| `inbox_dispatch.py` | Direct inbox.yaml reads | Read via DAOs. |
| `close.py` | Direct contract.yaml reads | Read via DAOs. |

### Modules to DELETE

| Module | Reason |
|--------|--------|
| `engine/parity.py` (~400 LOC) | No YAML to compare against |
| `engine/yaml_sync.py` (~180 LOC) | No dual-write queue needed |
| `commands/heal_parity.py` (~70 LOC) | No longer useful |
| `commands/archive_yaml.py` | Replace with `shux export-yaml` |
| `scripts/soak-monitor.py` | References parity directly |

### Partial deletion (strip YAML fallback paths)

| Module | What to remove |
|--------|---------------|
| `state_writer.py` | All `mirror_*()` functions. Keep only if export functionality stays. |
| `state_errors.py` | Remove `ParityError` — unused after migration |
| `db.py` | Remove `yaml_sync_queue` table from schema + migration |
| `doctor.py` | Remove parity check section |
| `dashboard-ui.py` | Remove SQLite parity panel |
| Every DAO module | Remove `_from_yaml()` fallback inside DAO methods (if any remain) |

### New module to create

| Module | Purpose |
|--------|---------|
| `commands/export_yaml.py` | `shux export-yaml` — generate YAML files from SQLite for human inspection/backup |
| `commands/import_yaml.py` | `shux import-yaml` — bulk-load YAML state into SQLite (one-time migration) |

### Shell scripts to update

| Script | Lines touching YAML | Action |
|--------|---------------------|--------|
| `scripts/delegate-to-claude.sh` | Reads contract.yaml for task context | Shell scripts should go through `shux` CLI, not read YAML directly |
| `scripts/delegate-to-codex.sh` | Same pattern | Same |
| `scripts/delegate-to-gemini.sh` | Same pattern | Same |
| `scripts/inbox-watch.sh` | Writes inbox.yaml | Already handled by `inbox_watch.py` |
| `scripts/inbox-dispatch.sh` | Reads inbox.yaml | Already handled by `inbox_dispatch.py` |
| Various guard/hygiene scripts | Read contract.yaml | Update to use `shux` CLI or read SQLite |

---

## Phased Plan

### Phase 0: Snapshot baseline (1 session)

- [ ] Run full test suite, capture results
- [ ] Run `shux export-yaml --all` to generate a complete YAML snapshot from current SQLite
- [ ] Commit the test snapshot as a CI baseline
- [ ] Feature-flag: add `SUPERHARNESS_SQLITE_ONLY=1` env var that exists but does nothing yet

**Success criteria:** All 2,565 tests pass. Export produces valid YAML matching current state.

### Phase 1: Switch all writes to SQLite-only (2-3 sessions)

Goal: Every write goes to SQLite. YAML files are NOT written. Feature-flag gated.

- [ ] **1a.** Add `SUPERHARNESS_SQLITE_ONLY` feature flag. When set, all YAML writes are no-ops.
  - Modify `contract_io.py`: skip YAML write when flag is set
  - Modify `state_writer.py`: skip YAML mirror when flag is set
  - Modify `lifecycle_rules.py`: skip `yaml.dump()` when flag is set
  - Modify `task.py`, `close.py`, `inbox_*.py`: skip YAML writes
  - Modify `dashboard-ui.py`: skip YAML writes

- [ ] **1b.** Remove YAML writes from `inbox_watch.py` (most complex file, 1,722 LOC). Replace each `yaml.dump()` with the equivalent DAO call.

- [ ] **1c.** Remove YAML writes from `dashboard-ui.py` (3,114 LOC). Replace each direct file write with DAO calls.

- [ ] **1d.** Remove `_sync_to_sqlite()` from `contract_io.py` — the SQLite write IS the write now. Remove the YAML write path entirely.

- [ ] **1e.** Run test suite with `SUPERHARNESS_SQLITE_ONLY=1`. Fix any tests that read YAML to assert state — redirect them to read SQLite.

**Success criteria:** All tests pass with the flag on. No YAML files are written. State is only in SQLite.

### Phase 2: Switch all reads to SQLite-only (2-3 sessions)

Goal: Every read comes from SQLite. Remove all YAML fallback paths. Still gated.

- [ ] **2a.** Strip `_from_yaml()` methods from `state_reader.py`. Remove `_get_backend()`. Every read path goes directly to the DAO.

- [ ] **2b.** Convert `lifecycle_rules.py` to read from SQLite via DAOs instead of `yaml.safe_load()`. (This is the most architecturally significant change — lifecycle_rules currently reads YAML directly.)

- [ ] **2c.** Convert all ~30 YAML reads in `dashboard-ui.py` to use `state_reader` or DAOs directly.

- [ ] **2d.** Convert all remaining YAML reads in `inbox_watch.py`, `task.py`, `inbox_dispatch.py`, `close.py`, `review_escalation.py`.

- [ ] **2e.** Run test suite. Tests that create YAML fixtures must now create SQLite state instead. Update test fixtures.

- [ ] **2f.** Remove `SUPERHARNESS_SCHEMA_ENFORCEMENT` — no more YAML contract to validate against.

**Success criteria:** All tests pass with the flag on. No YAML files are read for any operational purpose.

### Phase 3: Remove dual-write infrastructure (1-2 sessions)

Goal: Delete the modules that only existed for the dual-write system.

- [ ] **3a.** Delete `engine/parity.py`
- [ ] **3b.** Delete `engine/yaml_sync.py`
- [ ] **3c.** Delete `commands/heal_parity.py`
- [ ] **3d.** Remove `yaml_sync_queue` table from `db.py` schema + migration v3
- [ ] **3e.** Remove `ParityError` from `state_errors.py`
- [ ] **3f.** Remove parity panel from `dashboard-ui.py` (HTML + API endpoint)
- [ ] **3g.** Remove parity check from `doctor.py`
- [ ] **3h.** Remove parity check from `inbox_watch.py` `_sqlite_tick()`
- [ ] **3i.** Remove `mirror_*()` functions from `state_writer.py`. Keep the module if it provides useful write abstractions; otherwise delete it.
- [ ] **3j.** Remove `soak-monitor.py`
- [ ] **3k.** Run tests. Fix any remaining references to deleted modules.

**Success criteria:** Zero imports of parity, yaml_sync, heal_parity. State errors module has no parity references. All tests pass.

### Phase 4: Make SQLite-only the default (1 session)

Goal: Remove the feature flag. SQLite-only is the only mode.

- [ ] **4a.** Remove `SUPERHARNESS_SQLITE_ONLY` env var and all its conditionals
- [ ] **4b.** Remove `state_backend` from profile.yaml schema
- [ ] **4c.** Remove `_get_backend()` entirely
- [ ] **4d.** Update `init_project.py` — new projects no longer create YAML files
- [ ] **4e.** Run full test suite. Fix any test that passes `state_backend: dual` or reads non-existent YAML files.

**Success criteria:** Project initializes without YAML files. All operations work. All tests pass.

### Phase 5: YAML as export artifact (1-2 sessions)

Goal: Replace the YAML protocol files with an on-demand export/import system.

- [ ] **5a.** Build `commands/export_yaml.py`. `shux export-yaml` reads SQLite and writes:
  - `contract.yaml` (all tasks, subtasks, decisions, failures)
  - `inbox.yaml` (all inbox items)
  - `handoffs/` directory (all handoffs)
  - `decisions.yaml` (all decisions)
  - `failures.yaml` (all failures)

- [ ] **5b.** Build `commands/import_yaml.py`. `shux import-yaml` reads existing YAML files and bulk-loads into SQLite. One-shot for projects migrating from older superharness versions.

- [ ] **5c.** Add `shux init` deprecation warning: YAML files are now export-only. Print migration instructions for existing projects.

- [ ] **5d.** Update `AGENTS.md` template: remove references to reading `.superharness/contract.yaml` directly. Agents should use `shux contract` instead.

- [ ] **5e.** Update architecture docs.

**Success criteria:** `shux export-yaml` produces valid YAML identical to the pre-migration format. `shux import-yaml` bulk-loads a v1.40 project correctly. All docs updated.

### Phase 6: Port shell scripts (1-2 sessions) — OPTIONAL, can defer

- [ ] **6a.** Port `delegate-to-claude.sh` context-building logic to Python. Shell script becomes a thin launcher.
- [ ] **6b.** Same for `delegate-to-codex.sh` and `delegate-to-gemini.sh`.
- [ ] **6c.** Remove YAML reads from remaining shell scripts.

---

## Phase Dependency Map

```
Phase 0 (baseline)
    │
Phase 1 (write SQLite-only) ──→ Phase 3 (delete parity/sync)
    │                                │
Phase 2 (read SQLite-only)  ────────┘
    │
Phase 4 (remove feature flag)
    │
Phase 5 (export/import tools)
    │
Phase 6 (shell script cleanup)
```

Phases 1 and 2 can be partially parallelized — a write-only change in one module does not block a read-only change in another.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| SQLite concurrent write conflicts | Medium | High | WAL mode already in use. Add retry wrapper in `db.py` |
| Dashboard reads stale data during migration | Low | Medium | Feature-flag per phase. `SUPERHARNESS_SQLITE_ONLY=0` rollback |
| Handoff files (one-per-task YAML) lost | Low | High | Phase 5 export includes handoffs. Phase 0 snapshot as safety net |
| Shell scripts break (read YAML directly) | Medium | Low | Phase 6 ports them. Until then, scripts use `shux` CLI |
| Test fixture migration (YAML → SQLite) | High | Medium | Phases 1-2 each require fixture updates. Budget 20% of time per phase for test fixes |
| Dashboard reads ~30 YAML files | High | Medium | Largest surface area. Phase 2c is the riskiest single step |

---

## Estimated Effort

| Phase | Sessions | Risk |
|-------|----------|------|
| 0 — Baseline | 1 | Low |
| 1 — Write SQLite-only | 2-3 | Medium |
| 2 — Read SQLite-only | 2-3 | Medium |
| 3 — Delete parity/sync | 1-2 | Low |
| 4 — Remove feature flag | 1 | Low |
| 5 — Export/import tools | 1-2 | Low |
| 6 — Shell script cleanup | 1-2 | Low |
| **Total** | **9-14 sessions** | |

---

## Success Metrics

1. `parity.py`, `yaml_sync.py`, `heal_parity.py` no longer exist in the codebase
2. Zero `yaml.dump()` calls targeting `.superharness/` state files
3. Zero `yaml.safe_load()` calls targeting `.superharness/` state files (outside of `export_yaml.py` and `import_yaml.py`)
4. `db.py` has no `yaml_sync_queue` table
5. New project init creates no YAML files (only SQLite)
6. `shux export-yaml` produces YAML that a v1.40 reader can parse
7. All 2,565 tests pass (adjusted for removed modules)
8. Dashboard parity panel is gone
9. Feature flag `SUPERHARNESS_SQLITE_ONLY` is removed
10. Architecture doc reflects the new reality
