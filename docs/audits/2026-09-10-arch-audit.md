# Architecture Audit — superharness

**Date:** 2026-09-10
**Scope:** Broad structural review (post YAML→SQLite migration)
**Auditor:** OpenCode (arch-audit)

## Summary

The state core is sound and has held up well: 41 tables with versioned migrations (`CURRENT_SCHEMA_VERSION = 39`), savepoint rollback, `user_version` + `schema_migrations` reconciliation, foreign keys, 39 indexes, and all DDL centralized in `engine/db.py` (the only file with `ALTER TABLE`). The main risk is not the database; it is the growth of two god modules and a DAO boundary that is widely bypassed. `commands/inbox_watch.py` is now **5,594 lines** — up from 4,788 when the 2026-08-05 audit flagged it — and mixes reconciliation, dispatch, discussion flow, liveness, telemetry, and direct SQL. Around it, `commands/` opens the database directly at **254 call sites**. This is recoverable, but it is the single largest structural liability and it is getting worse, not better.

A note on the "add design patterns" premise: the patterns largely already exist. `engine/*_dao.py` (18 modules) is a Repository layer; `adapter_manifests/` + `resolve_launcher` is a Strategy/registry; `engine/next_action.py` is a state machine. Introducing more abstraction would **add** lines, not remove them. The leverage is decomposition and *enforcing* the boundaries that already exist.

## CRITICAL — fix before next deploy

None found. No data-loss or security-critical gap surfaced in this pass.

## HIGH — fix before scale

### 1. `inbox_watch.py` is a 5,594-line god module

- **Evidence:** `src/superharness/commands/inbox_watch.py` is 5,594 lines (was 4,788 at the 2026-08-05 audit); it references `get_connection` at **77 lines** and mixes lifecycle reconciliation, dispatch, discussion, liveness, and telemetry.
- **Risk:** every background change edits the same high-churn file; race and regression isolation is expensive.
- **Fix (one line):** extract one concern at a time behind an engine seam — start with a reconciliation service — leaving the command as composition only.
- **Phase:** its own phase, with a concurrency test per extracted slice.

### 2. The DAO boundary is bypassed at scale

- **Evidence:** `commands/` contains **254 `get_connection` references**; top offenders are `inbox_watch.py` (77), `task.py` (24), `inbox_dispatch.py` (18), `status.py` (16). There are also **12 raw `sqlite3.connect`** calls in `src/`, e.g. `engine/model_discovery.py:97`, `engine/operator_memory.py:59`, `mcp/session.py:60`, `commands/backup_state.py:47-48`.
- **Risk:** schema and migration behaviour are implemented inconsistently across direct call sites; raw connects that do not go through `engine/db.py:212-220` miss the mandatory PRAGMAs (`foreign_keys=ON`, `busy_timeout`, `journal_mode`), so a raw writer can silently skip FK enforcement.
- **Fix (one line):** route new state access through a DAO or a documented engine helper; migrate touched paths only.
- **Phase:** incremental, enforced by review rule; fold the raw `sqlite3.connect` sites into `get_connection` first.

### 3. Spec drift: a concept doc advertises commands that do not exist

- **Evidence:** `docs/CONCEPT-notifications-and-state-isolation.md:451-460` presents `shux state path|open|shell|dump` as available. `cli.py` registers only `backup-state`, `archive-yaml`, `export-yaml`, `import-yaml` (lines 313-328).
- **Risk:** a new user follows a public design doc to nonexistent commands and cannot tell a proposal from a supported surface.
- **Fix (one line):** banner the doc as a proposal, or rewrite those lines to the implemented CLI.
- **Phase:** documentation correction.
- **Note:** this is the same finding the 2026-08-05 audit raised; it is unresolved.

## MEDIUM — recoverable technical debt

### 4. Observability is print-first, not structured

- **Evidence:** `src/` has **1,242 `print(`** call sites versus **692 `logger.`**; no structured fields in log records.
- **Risk:** debugging a stuck daemon, a missing dispatch, or a slow cycle is grep-and-guess rather than query-by-field.
- **Fix (one line):** adopt one logging helper with stable fields (task_id, agent, phase) for engine/background paths; leave CLI user output on stdout.
- **Phase:** small, incremental.

### 5. Data-model invariants live in code, not constraints

- **Evidence:** across 41 `CREATE TABLE` statements there are only **2 `CHECK` constraints**; `tasks.extras_json` is `TEXT` with no validation (`engine/db.py:321`).
- **Risk:** JSON-in-TEXT columns drift with no guard; invalid shapes persist silently.
- **Fix (one line):** add `CHECK(json_valid(col))` where JSON is stored, and validate at the DAO edge for the rest.
- **Phase:** schema iteration (v40), with a migration test against pre-existing rows.

### 6. Error-handling patterns differ across modules

- **Evidence:** broad `except Exception:` handlers in commands, e.g. `adapter_payload.py:166`, `context.py:79`, `contract_today.py:201`, `dashboard.py:162/175/197`. No bare `except:` exists (good). Two warn-only paths are intentional and documented (`events` background writer, `context_dao.record_dispatch`).
- **Risk:** broad catches make a caller bug look like an infrastructure outage.
- **Fix (one line):** narrow the broad catches to the exception types actually expected, or log with the exception attached.
- **Phase:** opportunistic, per touched file.

### 7. Circular-import workarounds signal a graph problem

- **Evidence:** `engine/handoffs_dao.py:33` documents a leaf-DAO import cycle; `modules/loader.py:15` lazily imports its validator to avoid a cycle; god modules import the DB directly.
- **Risk:** rename/refactor operations break in non-obvious ways.
- **Fix (one line):** keep DAOs as leaves and move shared types into `engine/schemas.py` rather than importing peer DAOs.
- **Phase:** with finding 2.

## LOW — nice-to-have polish

- **Concurrency posture is good but bypassable.** SQLite runs WAL with `busy_timeout` (5000/15000) and `foreign_keys=ON` centrally in `engine/db.py:212-220`, and `tests/chaos/test_concurrent_writers.py` exists. The gap is raw connects that skip these PRAGMAs (finding 2).
- **Backup covers only `state.db`.** `commands/backup_state.py` backs up/restores the project state DB; `engine/model_discovery.py` keeps its own DB (`sqlite3.connect(self._db_path)`), which is not in the backup path.
- **Version provenance exists but is thin.** `superharness.__version__` comes from package metadata; the dashboard has `version_sanity` (`scripts/dashboard-ui.py:223`). There is no single deploy-stamp endpoint beyond this.
- **Dashboard security is correctly scoped.** Loopback bind (`dashboard-ui.py:2104`), host allowlist (`:2107`), per-project token with `chmod(0o600)` (`:4787`) match the ARCHITECTURE.md security claims.

## Out of scope

- Business-logic correctness, UI/UX, provider cost policy, and live host configuration.
- Migration-consistency of the `tasks.extras_json` column (not sampled).

## Recommended next iterations

1. **Watcher decomposition** — extract a reconciliation service from `inbox_watch.py` with an end-to-end concurrency test; the file has grown since the last audit.
2. **DAO-boundary ratchet** — fold the 12 raw `sqlite3.connect` sites into `get_connection`, then add a lint/test that rejects new direct SQL in `commands/`.
3. **Doc-truth pass** — fix `CONCEPT-notifications-and-state-isolation.md` (findings 3), the one live spec-drift item.
4. **Observability helper + JSON CHECK constraints** — bundle as one small "operational hygiene" iteration (findings 4 and 5).
