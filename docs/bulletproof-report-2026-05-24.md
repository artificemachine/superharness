# Bulletproof Report — 2026-05-24

**SCOPE:** superharness (Python). General audit — all doctrine files, engine, commands, scripts. Audit mode (read-only).

---

## CLAIMS AUDITED

| Claim | Source | Verdict | Evidence |
|-------|--------|---------|----------|
| "Migration complete as of 2026-05-24. All operational state reads are routed through DAOs." | `engine/sqlite_only.py:3-4` | **VERIFIED** | `test_no_state_yaml_reads.py` BASELINE is empty; ratchet scanner finds 0 offenders. |
| "YAML files are export-only artifacts; they are never read as authoritative input." | `engine/sqlite_only.py:6` | **VERIFIED** | Ratchet scanner (regex + AST taint union) finds 0 offenders across commands/, engine/, mcp/, scripts/. The two previously noqa'd reads (delegate.py:967, init_project.py:524) are .md instruction files, not state artifacts. |
| "contract.yaml, inbox.yaml, failures.yaml, decisions.yaml are DEAD" | `CLAUDE.md:9` | **VERIFIED** | Direct probe found 0 live reads of these files outside the allowlisted export writers. |
| "engine/state_reader.py → read API (always SQLite)" | `AGENTS.md:63` | **VERIFIED** (with caveat) | Production path (`_production_path=True`) routes exclusively to SQLite. Legacy YAML ingest runs only inside pytest (`_is_running_tests()` gate). The `yaml_only` emergency rollback mode exists in the env-var API but is not exercised by any production caller. |
| "engine/contract_io.py → canonical contract write path (SQLite, atomic tempfile)" | `AGENTS.md:61` | **VERIFIED** | `contract_io.py:201,213` uses `tempfile.mkstemp` + `os.replace`. |
| "parity checking is no longer needed / deprecated / always returns healthy" | `engine/parity.py:4,36,41` | **VERIFIED** (stub is correct, callers are absent) | `check_parity` and `heal_parity` are no-op stubs. No live caller outside parity.py itself. |
| "handoffs_fts dead AND misconfigured" | `docs/PLAN-sqlite-source-of-truth-refactor.md:17` | **VERIFIED** | v23 migration (`db.py:676`) drops `handoffs_fts`. v23 is registered in `_MIGRATIONS` at position 23 (`db.py:702`). |
| "yaml_sync.py — no-op stubs. Will be deleted entirely in Phase 4." | `engine/yaml_sync.py:5` | **VIOLATED** | `yaml_sync.py` still exists (32 lines). Its callers (`inbox_watch.py:86,117,149`, `inbox_dispatch.py:522`) still import and call `yaml_sync.enqueue_op` — a no-op, so correct at runtime, but the deletion promised in the docstring has not occurred. |
| "CI auto-tags and publishes to PyPI on every push to main" | `CLAUDE.md:83` | **VIOLATED** | `release.yml` fires only on `v*` tag push, not on merge to main. `publish.yml` fires on `release: published` or manual `workflow_dispatch`. Nothing auto-fires on a PR merge. The claim is wrong — tags and releases require explicit `/ship-release` or manual `git push --tags`. |
| "CHANGELOG.md is append-only — enforced by pre-commit" | `AGENTS.md:33`, `CLAUDE.md:11` | **VERIFIED** | `check-changelog-append-only.sh --staged` runs in `.githooks/pre-commit:6` (local) and `.github/workflows/tests.yml:30` (CI). |

---

## HONESTY SCORE: 8/10 completion-claims true.

Two violations. One is a docs lie (`yaml_sync.py` deletion not done). One is a CI mis-statement (releases are not automatic on merge to main). The core SQLite-is-SoT invariant is now mechanically enforced and fully verified.

---

## DRIFT-CLASS FINDINGS

**Dead code that looks live:**
- `engine/yaml_sync.py` — promised deleted in Phase 4, still present. Its callers import and invoke it for the no-op side-effect. Low risk (all stubs), but the file is dead code with living callers. The table it queues to (`yaml_sync_queue`) is still in the DB schema and has two indexes.
- `engine/parity.py` — `check_parity`, `heal_parity` are no-op stubs with zero callers in production. `state_errors.ParityError` is defined but never raised. Dead but harmless.
- `engine/state_writer.py:319` — `backfill_handoffs_from_yaml` has 2 test references but 0 production callers. Exists as a one-time import bridge; not dead-dangerous, but untested in prod.
- `engine/parallel_dispatch.py:147` — `fanout_dispatch` has 4 test refs but 0 production callers.
- `engine/swarm.py:101` — `swarm_dispatch` same pattern (4 test refs, 0 production).

**Silent-success risk:**
- `state_reader.py` has a broad `except Exception: logger.warning ... return []` pattern inside `get_ledger_entries` (line ~429). A SQLite schema mismatch returns empty list silently, not an error. This is intentional resilience but means a broken ledger table is invisible to callers.
- `engine/behavioral.py:432,465` — bare `except Exception: pass` blocks. If the behavioral profile write fails silently, the agent learns nothing and no alarm fires.

**Unenforced invariants:**
- `yaml_sync.py` deletion is promised in the docstring but has no test that would fail while the file still exists (a simple `assert not Path("engine/yaml_sync.py").exists()` guard would enforce it).
- The "CI auto-tags on merge to main" claim in `CLAUDE.md` is simply wrong and will mislead future agents into skipping a manual tag step after merge. Should be corrected, not guarded.

---

## REMEDIATION

**Manifest (entity → `{writer_uses_db, reader_uses_db, no_yaml_reader}`):**

| Entity | writer_uses_db | reader_uses_db | no_yaml_reader | Status |
|---|---|---|---|---|
| tasks | ✓ | ✓ | ✓ | DONE |
| inbox | ✓ | ✓ | ✓ | DONE |
| decisions | ✓ | ✓ | ✓ | DONE |
| failures | ✓ | ✓ | ✓ | DONE |
| discussions | ✓ | ✓ | ✓ | DONE |
| ledger | ✓ | ✓ | ✓ | DONE |
| handoffs | ✓ | ✓ | ✓ | DONE |

All entities DONE. The manifest is fully green for the first time.

**Corrections needed (not guard-able, require doc edits):**
1. `CLAUDE.md:83` — fix "CI auto-tags and publishes to PyPI on every push to main" → "CI publishes to PyPI when a `v*` tag is pushed via `/ship-release`."
2. `engine/yaml_sync.py:5` — delete the file (and its callers' import lines) or remove the "Will be deleted entirely in Phase 4" claim.

**Guard already in place:**
- `tests/test_no_state_yaml_reads.py` — ratchet guard (BASELINE empty). Any new state YAML read fails CI immediately.

---

## PROGRESS (vs 2026-05-22 baseline)

| Claim | 2026-05-22 | 2026-05-24 | Movement |
|---|---|---|---|
| "Migration complete" | VIOLATED | VERIFIED | FIXED |
| "All state lives in SQLite" | VIOLATED | VERIFIED | FIXED |
| "YAML files no longer read operationally" | VIOLATED | VERIFIED | FIXED |
| "contract/inbox/failures/decisions DEAD" | VERIFIED | VERIFIED | held |
| "state_reader always SQLite" | (not audited) | VERIFIED | new |
| "parity deprecated" | (noted as drift) | VERIFIED | FIXED |
| "handoffs_fts removed" | (noted as drift) | VERIFIED | FIXED |
| "yaml_sync.py deleted in Phase 4" | (noted as drift) | VIOLATED | persists |
| "CI auto-tags on merge to main" | (not audited) | VIOLATED | new finding |
| "CHANGELOG append-only enforced" | (not audited) | VERIFIED | new |

**Net: 3 VIOLATED → VERIFIED. 2 remain or are newly surfaced. The core invariant is mechanically enforced.**
