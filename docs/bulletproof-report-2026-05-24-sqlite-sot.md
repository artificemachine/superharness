# Bulletproof Report — 2026-05-24 (Focused: "SQLite is Single Source of Truth")

**SCOPE:** superharness (Python). Focused invariant audit — "SQLite is single source of truth."
All probes are deterministic grep/AST reads across `src/superharness/`, `tests/`. Audit mode (read-only).

---

## CLAIMS AUDITED

| Claim | Source | Verdict | Evidence |
|-------|--------|---------|----------|
| "State lives in SQLite — contract.yaml, inbox.yaml, failures.yaml, decisions.yaml are DEAD" | `CLAUDE.md:9` | **VERIFIED** | Ratchet BASELINE is empty (0 entries). `test_no_state_yaml_reads.py` passes. No live operational reads of the four named files. |
| "All operational state reads are routed through DAOs / state_reader" | `engine/sqlite_only.py:3-4` | **VERIFIED** | Ratchet scanner (regex + AST) finds 0 offenders. `get_ledger_entries`, `get_handoffs`, `get_inbox_items`, `get_contract_doc` all route to SQLite in production. |
| "YAML files are export-only artifacts; they are never read as authoritative input" | `engine/sqlite_only.py:6` | **VERIFIED** | Core state files: 0 live readers outside export writers. One drift note: `contract_io.read_contract` opens `contract.yaml` as a `setdefault` fallback for top-level metadata — SQLite wins on any conflict, YAML only fills gaps. Redundant since `project_meta` table holds the same data. |
| "handoff YAML readers migrated to SQLite" | (implied by yaml_sync deletion, inbox_watch migration) | **VERIFIED** | `_auto_close_report_ready` now queries `handoffs_dao.get_latest()`. `yaml_sync.py` deleted. Zero production calls to `yaml_sync.enqueue_op`. |
| "yaml_sync.py deleted in Phase 4" | `engine/yaml_sync.py:5` (former) | **VERIFIED** | File deleted via `git rm` in this session. Callers (`inbox_watch.py`, `inbox_dispatch.py`, `archive_yaml.py`) stripped of import + call sites. |
| "state_reader always SQLite in production (`_production_path=True`)" | `AGENTS.md:63` | **VERIFIED** | `_production_path()` returns `True` outside pytest. `yaml_only` emergency mode exists but requires explicit `STATE_READER_FORCE=yaml_only` env-var — never triggered in normal production. |

---

## HONESTY SCORE: 6/6 SoT-related claims VERIFIED.

No violations. The "SQLite is single source of truth" invariant is mechanically enforced and holds for all operational reads. Two drift findings remain (maintenance items, not correctness failures).

---

## PROBE LOG — CANDIDATES CLASSIFIED

### Probe A — `init_project.py:312`: writes `ledger.md` as bootstrap scaffold
**Classification: LEGITIMATE EXCEPTION.** One-time initialization write. No read of YAML as authoritative state. `ledger.md` is not in the "DEAD" file list.

### Probes B/C — `handoff_write.py`, `mcp/tools/handoffs.py`: unconditional YAML write alongside SQLite in `upsert_handoff`
**Classification: LEGITIMATE EXPORT WRITE.** SQLite is written first (authoritative). YAML written as compat side-effect. All handoff READERS now query SQLite via `handoffs_dao.get_latest()`. The YAML write is now technically export-only. Drift: docstring says "readers not yet migrated" — stale as of this session.

### Probes D/E — `state_writer.upsert_handoff` called from `close.py:217`
**Classification: LEGITIMATE EXPORT WRITE.** Same pattern as B/C. `write_handoff_to_db` is called first; YAML write follows as compat export. SQLite is authoritative.

### Probe F/G — `contract_io.read_contract:248-249`: reads `contract.yaml` for top-level metadata in sqlite_only mode
**Classification: DRIFT (redundant fallback, not a violation).** Code flow: `state_reader.get_contract_doc()` reads `id` and `goal` from `project_meta` SQLite table first. Then if `contract.yaml` exists, opens it and calls `setdefault` — SQLite values are never overridden by YAML. The YAML fallback is redundant since `project_meta` provides the same fields. Not a SoT violation (SQLite wins on conflict) but is a live YAML read that can be deleted.

### Probe H — `get_contract_doc` reads from `project_meta` SQLite table
**Classification: CLEAN.** Pure SQLite read. Not a violation.

### Probe I — `yaml_only` mode in `state_reader`
**Classification: LEGITIMATE EMERGENCY ROLLBACK.** Requires `STATE_READER_FORCE=yaml_only` env-var. Not triggered in any production path. Exists as break-glass mechanism; its presence does not falsify the production-path claim.

### Probe J — Multiple `ledger.md` writers (`close.py`, `verify.py`, `heartbeat.py`, `inbox_watch.py`, `subtask_cancel.py`, `dashboard-ui.py`, `onboard.py`, `pack.py`, `validate.py`, `context.py`)
**Classification: CLEAN (writes and non-content reads only).**
- `close.py`, `verify.py`, `inbox_watch.py`, `subtask_cancel.py`, `heartbeat.py` (line 60), `onboard.py`, `pack.py`, `validate.py`: append-only WRITES to ledger.md. Creating display artifact; not reading as authoritative state.
- `heartbeat.py:31-36`: reads `os.path.getmtime(ledger)` — file mtime only, not content. Health signal, not state read.
- `validate.py:74`: checks file existence; writes repair entries. Not reading as authoritative state.
- `context.py:308-315`: passes `ledger_path` to `_ledger_lines_for_task()`, but that function ignores the path and reads from `state_reader.get_ledger_entries()` (SQLite). `ledger_path` used only to derive `project_dir`. FALSE POSITIVE — pure SQLite read.

---

## DRIFT-CLASS FINDINGS

**Stale docstring:**
- `engine/state_writer.py:upsert_handoff` — comment "readers not yet migrated to the DB" is now false. All handoff readers use `handoffs_dao`. Safe to update.

**Redundant YAML fallback:**
- `engine/contract_io.py:read_contract` (lines ~248-259) — opens `contract.yaml` in sqlite_only mode to `setdefault` top-level metadata. The same data lives in `project_meta` SQLite table, making this read unreachable for any project where `shux init` ran correctly. Removing the block would make the code cleaner and would eliminate the only remaining YAML-open in the sqlite_only read path.

**No unenforced invariants discovered:**
- The ratchet guard (`tests/test_no_state_yaml_reads.py`, BASELINE empty) enforces the no-YAML-read invariant for the four named dead files.
- No test enforces "contract.yaml fallback block is removed" — that deletion is not yet guarded.

---

## REMEDIATION

| Item | Action | Priority |
|------|--------|----------|
| Update `upsert_handoff` docstring | Remove "readers not yet migrated" comment | Low |
| Delete YAML fallback in `contract_io.read_contract` (lines ~248-259) | Remove the `if os.path.exists(path): open(path)` block | Medium |
| Add guard test | `assert not Path(".superharness/contract.yaml").exists() or contract_io only uses SQLite` — optional; redundant since existing ratchet already covers this | Low |

Neither item is a SoT correctness failure. Both are maintenance cleanup.

---

## PROGRESS (vs 2026-05-24 general audit baseline)

| Claim | General Audit (2026-05-24) | Focused Audit (2026-05-24) | Movement |
|-------|---------------------------|---------------------------|----------|
| "Migration complete / all reads routed through DAOs" | VERIFIED | VERIFIED | held |
| "YAML files export-only" | VERIFIED | VERIFIED (with drift note) | held |
| "yaml_sync.py deleted" | VIOLATED → FIXED in session | VERIFIED | held |
| "CI auto-tags on merge" | VIOLATED → FIXED in session | n/a (CI doc, not SoT) | n/a |
| "handoff readers migrated" | (not audited) | VERIFIED | new |
| "state_reader always SQLite in prod" | VERIFIED | VERIFIED | held |
| `contract_io` YAML fallback | (not audited) | DRIFT (redundant, not violation) | new finding |
| `upsert_handoff` stale docstring | (not audited) | DRIFT (comment rot) | new finding |

**Net: 0 VIOLATED. 2 new DRIFT findings (maintenance-only). The core SoT invariant is clean.**
