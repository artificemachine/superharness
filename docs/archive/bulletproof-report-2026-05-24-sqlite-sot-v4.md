# Bulletproof Report — "SQLite is Single Source of Truth"
**Date:** 2026-05-24 (v4 — post DAO bypass fix)
**Focus invariant:** SQLite is single source of truth
**Mode:** audit
**Prior baseline:** bulletproof-report-2026-05-24-sqlite-sot-v3.md (2 violations)

---

## SCOPE

Python multi-agent session handoff CLI (`superharness`). Source under
`src/superharness/` — 80+ command modules, 60+ engine modules. Doctrine in
`CLAUDE.md`, `AGENTS.md`, `src/superharness/engine/sqlite_only.py`,
`IMPLEMENTATION-status.md`. Guard: `tests/test_no_state_yaml_reads.py`.

---

## CLAIMS AUDITED

| # | Claim | Source | Verdict | Evidence |
|---|-------|--------|---------|----------|
| C1 | "contract.yaml, inbox.yaml, failures.yaml, decisions.yaml are DEAD" | CLAUDE.md:9, AGENTS.md:31 | **VERIFIED** | `contract_io.py:237–243` gates the YAML path behind `is_sqlite_only()` — unreachable in production. No YAML state reads in operational flow. |
| C2 | "All operational state reads routed through DAOs / state_reader" | `sqlite_only.py:3` | **VERIFIED** | `discussions_dao.register_yaml_submission` reads agent-written round YAML — this is the ingest boundary (agents are external, harness imports to SQLite). Not a bypass. All other reads use `state_reader` or DAO `get_*` methods. |
| C3 | "YAML files never read as authoritative input" | `sqlite_only.py:6`, `IMPLEMENTATION-status.md:3` | **VERIFIED** | All remaining `yaml.safe_load` calls read: config (profile.yaml, workflow.yaml, schedule.yaml, heartbeat config), agent status signals, adapter manifests, or agent-output boundaries. `inbox_dispatch.py:538` reads cost-cache (derived artifact). `inbox_dispatch.py:974` parses YAML from agent log text — not a state file read. |
| C4 | "All YAML runtime read/write paths eliminated" | `IMPLEMENTATION-status.md:60` | **VERIFIED** | `_claim_next_item` else-branch deleted — returns `1` with error message (inbox_dispatch.py:730–735). `_reconcile_state`'s `_set_inbox_status` calls route through `_inbox_cmd` → `inbox.py set_status handler` → `inbox_dao.update_status()` → SQLite. Not a YAML write. |
| C5 | "ratchet guard BASELINE is empty" | `tests/test_no_state_yaml_reads.py:4` | **VERIFIED** | `BASELINE: set[str] = set()`. Confirmed empty. YAML read regression gate passes CI. |
| C6 | "handoffs_fts dead AND misconfigured" | prior plan doc | **VERIFIED** | Dropped unconditionally in migration v23. Zero query sites remain. |
| C7 | "yaml_sync_queue dropped (dead table)" | prior plan doc | **VERIFIED** | Migration v24 (`_migration_v24`) runs `DROP TABLE IF EXISTS yaml_sync_queue`. `CURRENT_SCHEMA_VERSION=24`. Confirmed dropped. |
| C8 | "yaml_sync.py deleted" | prior plan doc | **VERIFIED** | File absent. Zero import sites. |

---

## HONESTY SCORE: 8/8 verified. Both prior violations (C4, C7) are fixed. SQLite SoT invariant holds end-to-end.

---

## DRIFT-CLASS FINDINGS

### DAO Encapsulation Gaps (not SoT violations — SQLite is still written; DAO abstraction is incomplete)

The following sites write to SQLite directly, bypassing `inbox_dao`. They are
NOT "YAML as SoT" violations — the data lands in SQLite — but they widen the
surface area for schema changes and status-transition bugs. Categorised as
**DAO coverage drift**, tracked separately from the SoT invariant.

**Fixed this session (8 sites):**
- `inbox_watch.py:1313` → `inbox_dao.set_plan_only()`
- `inbox_watch.py:1568` → `inbox_dao.mark_done()`
- `inbox_watch.py:1747` → `inbox_dao.mark_done()`
- `inbox_watch.py:3550` → `inbox_dao.mark_stale()`
- `status.py:624` → `inbox_dao.mark_stale()`
- `status.py:643` → `inbox_dao.mark_stale()`
- `status.py:668` → `inbox_dao.mark_stale()`
- `status.py:738` → `inbox_dao.mark_stale()`

**Remaining (10 sites — no DAO equivalent exists yet):**

| File | Line | Pattern | Missing DAO function |
|------|------|---------|---------------------|
| `inbox_watch.py` | 1381 | `UPDATE inbox SET status='failed', failed_reason=?, failed_at=?` | `inbox_dao.mark_failed(reason, now)` |
| `inbox_watch.py` | 1470 | Multi-field reassignment UPDATE (target_agent, retry_count, max_retries, pid) | `inbox_dao.reassign(agent, retries, reason, now)` |
| `inbox_watch.py` | 1687 | Multi-field recovery UPDATE (recovery_count, target_agent, failed_reason, retry_count) | `inbox_dao.mark_recovered(recovery_count, agent, reason, now)` |
| `inbox_watch.py` | 3086 | Exception fallback `UPDATE inbox SET status=?` after `update_status()` raises | Fallback can be removed if `update_status()` is made to never raise |
| `status.py` | 719 | `DELETE FROM inbox WHERE status='stale'` (bulk purge) | `inbox_dao.purge_stale()` |
| `state_writer.py` | 219 | Dynamic column UPDATE (non-status fields only) | `inbox_dao.set_fields(id, **fields)` |
| `state_writer.py` | 574 | Same pattern in `_mirror_inbox_to_sqlite` | same |
| `inbox.py` | 376 | `DELETE FROM inbox WHERE id=?` (remove command) | `inbox_dao.remove(id)` |
| `inbox.py` | 397 | Dynamic `UPDATE inbox SET {key}=?` (set_field command) | `inbox_dao.set_field(id, key, value)` |
| `dashboard-ui.py` | 2450 | `DELETE FROM inbox WHERE id=?` (belt-and-suspenders cleanup after `_inbox_cmd remove`) | redundant if `inbox_dao.remove()` exists |

### Silent-success risk: subprocess roundtrip as DAO bridge

`_reconcile_state` in `inbox_dispatch.py` uses `_set_inbox_status` → `_inbox_cmd`
(subprocess) → `inbox.py set_status handler` → `inbox_dao.update_status()`.
This is a correct SQLite write, but uses a subprocess roundtrip for in-process
logic. If `inbox.py` is not importable (e.g. broken dependency), the status
update silently fails and the inbox item stays in `launched`. The risk is not
SoT correctness but resilience. Mitigation: replace `_inbox_cmd`/`_set_inbox_status`
calls in `_reconcile_state` with direct `inbox_dao` calls (same refactor pattern
as `_claim_next_item`).

### Unenforced invariant: DAO write coverage

The YAML read invariant has a CI guard (`test_no_state_yaml_reads.py`). The DAO
write coverage invariant (all inbox mutations through `inbox_dao`) has NO guard.
The 10 remaining raw SQL sites can regress silently. A sibling guard
(`test_no_raw_inbox_sql.py`) would enforce this mechanically.

---

## REMEDIATION

### Manifest (per entity — what must hold for "done")

```
inbox DAO coverage:
  [x] inbox_dao.claim_next()           — claim (SQLite-native)
  [x] inbox_dao.update_status()        — status transitions
  [x] inbox_dao.mark_stale()           — orphan/cleanup
  [x] inbox_dao.mark_done()            — lifecycle done
  [x] inbox_dao.set_plan_only()        — flag mutation
  [x] inbox_dao.set_retry()            — retry reset
  [ ] inbox_dao.mark_failed(reason, now)   — failed with timestamps
  [ ] inbox_dao.reassign(agent, ...)       — fallback reassignment
  [ ] inbox_dao.mark_recovered(...)        — recovery rotation
  [ ] inbox_dao.purge_stale()             — bulk DELETE stale
  [ ] inbox_dao.set_fields(**fields)       — arbitrary field update
  [ ] inbox_dao.remove(id)                — DELETE by id
  [ ] inbox_dao.set_field(id, key, value) — single field update

SQLite SoT invariant:
  [x] YAML claim path deleted (C4 fixed)
  [x] yaml_sync_queue table dropped (C7 fixed)
  [x] BASELINE empty in YAML read guard
  [x] contract_io YAML fallback gated by is_sqlite_only()
```

### Guard (recommended, not yet written)

Write `tests/test_no_raw_inbox_sql.py` to grep/AST-scan for
`conn.execute.*UPDATE inbox|conn.execute.*DELETE FROM inbox|conn.execute.*INSERT INTO inbox`
outside `inbox_dao.py`. Exempt the 10 remaining sites with a named BASELINE
(same ratchet pattern as `test_no_state_yaml_reads.py`). Fails CI if a new
raw site is added.

---

## PROGRESS (vs bulletproof-report-2026-05-24-sqlite-sot-v3.md, same day)

| Claim | v3 verdict | v4 verdict | Delta |
|-------|-----------|-----------|-------|
| C1 YAML state files dead | VERIFIED | VERIFIED | held |
| C2 all reads through DAOs | VERIFIED | VERIFIED | held |
| C3 YAML never authoritative | VERIFIED | VERIFIED | held |
| C4 YAML paths eliminated | **VIOLATED** | **VERIFIED** | **FIXED** |
| C5 BASELINE empty | VERIFIED | VERIFIED | held |
| C6 handoffs_fts dead | VERIFIED | VERIFIED | held |
| C7 yaml_sync_queue dropped | **VIOLATED** | **VERIFIED** | **FIXED** |
| C8 yaml_sync.py deleted | VERIFIED | VERIFIED | held |
| Raw inbox DAO bypasses (drift) | 8 sites (inbox_watch+status) | 10 remaining sites (state_writer, inbox.py, dashboard-ui, inbox_watch) | 8 fixed, 10 remain (no DAO equivalent) |

**Net: 2 violations → 0 violations. Honesty score: 6/8 → 8/8.**

The SQLite SoT invariant is now fully verified. Remaining work is DAO
completeness (adding 7 missing DAO functions to eliminate 10 raw SQL sites),
not SoT correctness.
