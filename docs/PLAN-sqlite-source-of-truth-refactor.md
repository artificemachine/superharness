# PLAN — SQLite Source-of-Truth Refactor

**Date:** 2026-05-22
**Status:** proposed (investigation complete, not yet approved)
**Supersedes scope of:** `PLAN-negative-knowledge-retention.md` (that feature becomes a near-free downstream benefit of this refactor — see §8)
**Driver:** `engine/sqlite_only.py` declares *"the YAML→SQLite migration is complete; YAML is no longer read or written for operational purposes."* A code audit proves this is **false** for handoffs and ledger. Many code paths still treat export artifacts as authoritative state. This plan closes the gap so the doctrine becomes true.

---

## 1. The core finding (this drives everything)

**Handoffs are the keystone, and they are not in SQLite at all operationally.**

- **No writer populates the `handoffs` table.** `state_writer.upsert_handoff`, `commands/handoff_write.py`, and `mcp/tools/handoffs.py:write_handoff` all write **YAML files only** — none call `handoffs_dao.append`. The only code that ever INSERTs a handoff is the one-time `migrate_yaml.py`. So the table is empty/stale in practice.
- **Therefore every reader globs YAML.** ~19 violation sites across 8 files read `.superharness/handoffs/*.yaml` (or `ledger.md`, or discussion `state.yaml`) directly.
- **The read API is incomplete.** `handoffs_dao` offers only `get_history(task_id)` and `get_latest(task_id, phase)` — no "all handoffs", no "by recipient", no search. That absence is *why* callers fall back to globbing.
- **`handoffs_fts` is dead AND misconfigured** — declares columns (`agent`, `summary`) that don't exist in `handoffs` (real: `from_agent`, `to_agent`, `metadata`); never written, never queried.

The order of operations matters: you cannot point readers at SQLite until SQLite actually holds the data. **Writers and read-APIs come before reader migration.**

---

## 2. Entity-by-entity status (from audit)

| Entity | DB writer wired? | DB read API complete? | Difficulty |
|---|---|---|---|
| **tasks** | Yes (`contract_io`/`tasks_dao`) | Yes (`state_reader`) | Done — only vestigial YAML plumbing remains |
| **inbox** | Yes (`inbox_dao`) | Yes | Done |
| **discussions** | Yes (`discussions_dao`, incl. YAML→DB round ingest) | Yes (`get`, `get_rounds`) | **Easy** — readers just swap to DAO |
| **ledger** | Partial — `ledger_dao.record` exists; verify all writers | Reader exists but `state_reader.get_ledger_entries` still merges `ledger.md` | **Medium** — must not lose markdown-only history |
| **handoffs** | **NO** — all writers YAML-only | **NO** — only task-scoped reads | **Hard** — critical path |
| **failures / decisions** | Yes (`record`) | Yes (`get_recent`) but not exposed via recall | Easy once recall reads DB |

Legitimately YAML (NOT refactor targets): config files (`profile.yaml`, `watcher.yaml`, `heartbeat.yaml`, `scheduled.yaml`), `agents/*.status.yaml` (no DB table for agent liveness — out of scope), behavioral-profile JSON, MCP config, operational logs, the discussion round-submission ingest bridge, and `shux export-yaml` outputs.

---

## 3. Phased plan

Ordered by dependency and risk. Each phase is independently shippable and leaves the system consistent.

### Phase 0 — Dead-code removal (no behavior change, de-risks later phases)
Pure deletions of confirmed-inert code. Safe to ship first.
- Drop `handoffs_fts` table + creation (db.py migration v6) via a new migration `DROP TABLE IF EXISTS handoffs_fts`.
- Drop the inert `yaml_sync_queue` table + dedup index, and remove the no-op `engine/yaml_sync.py` stubs and their dead callers (`archive_yaml.py:54`).
- Remove unreachable code in `state_reader.get_handoffs` (dead lines after the `return`, ~313-322).
- **RED:** a test asserting these symbols/tables are gone; a smoke test that migrations apply cleanly on a fresh + existing DB.
- **Done when:** suite green, no references to the dropped symbols remain.

### Phase 1 — Make handoffs live in SQLite (the keystone)
- **Write path:** route `state_writer.upsert_handoff`, `commands/handoff_write.py`, and `mcp/tools/handoffs.py:write_handoff` through `handoffs_dao.append` (in sqlite_only mode). YAML emission becomes export-only (gated like `_export_contract_yaml`), not the operational store.
- **Backfill:** one-time migration that ingests existing `.superharness/handoffs/*.yaml` into the `handoffs` table so no history is lost. (Reuse the `migrate_yaml.py` insert logic.)
- **Read API:** add to `handoffs_dao`: `get_all(conn, limit, since)`, `get_for_agent(conn, to_agent)`, and a search (`LIKE` over `content`/`metadata`; no FTS yet — see advice). Expose via `state_reader.get_handoffs` (already exists; fix it to read the now-populated table).
- **RED:** test that after `write_handoff`, the row is in the `handoffs` table (currently fails); test that `get_all`/`get_for_agent` return it.
- **Done when:** handoffs are written to and read from SQLite; YAML files are byte-for-byte the same export but no longer the source.

### Phase 2 — Ledger consolidation
- Verify every `ledger.md` writer also writes via `ledger_dao.record` (or migrate writers).
- Backfill any markdown-only ledger entries into the `ledger` table.
- Remove `_ledger_from_markdown` merge from `state_reader.get_ledger_entries` so the reader is pure-SQLite.
- **RED:** test that a ledger entry written operationally appears via `ledger_dao.get_recent` without touching `ledger.md`.
- **Done when:** `ledger.md` is export-only; no reader depends on it.

### Phase 3 — Migrate readers to SQLite (entity by entity, easiest first)
Now that the data is in the DB, repoint the ~19 violation sites:
- **3a Discussions (easy):** dashboard sites #16–18 → `discussions_dao.get` / `get_rounds`. No new DAO work.
- **3b Ledger readers:** `engine/recall.py:143`, `commands/context.py:85`, `mcp/tools/ledger.py`, `dashboard-ui.py:130` → `ledger_dao`.
- **3c Handoff readers:** `engine/recall.py:69`, `commands/context.py:65`, `commands/task.py:353` (→ `get_latest(task_id,"plan")`), `commands/delegate.py:166` (→ `get_for_agent`), `commands/contract_today.py:160`, `mcp/tools/handoffs.py:get_handoffs`, dashboard #12–15 → the new `handoffs_dao` readers.
- **3d Dashboard confirm-plan (#15):** the read+rewrite of YAML becomes a DB update through the normal status path.
- **RED per site:** behavior-parity test (same results from DB as the old glob produced), including snippet/date quality so output doesn't regress.
- **Done when:** no operational code path reads `.superharness/` state files; only config + export remain.

### Phase 4 — Enforce (prevent regression)
- Add a guard test / lint that fails CI if new code under `commands/`, `engine/`, `mcp/`, `scripts/` reads a `.superharness/{handoffs,discussions}/` glob or `ledger.md` / `contract.yaml` / `inbox.yaml` as input. Allowlist the export writers and config readers.
- Update `sqlite_only.py` docstring and `CLAUDE.md` to state which YAML reads remain *legitimately* (config + agent status + ingest bridge), so the doctrine matches reality precisely.
- **Done when:** the guard is green and documented.

---

## 4. TDD summary

| Phase | RED | GREEN | REFACTOR |
|---|---|---|---|
| 0 | dropped symbols still present | migrations drop them | — |
| 1 | written handoff absent from table | writers → `handoffs_dao.append`; backfill; new readers | unify YAML emit behind export gate |
| 2 | ledger entry not in DB without `.md` | writers → `ledger_dao`; backfill | remove markdown merge |
| 3 | each site: DB result ≠ glob result | repoint to DAO/state_reader | shared "match + source-tag" helper for recall |
| 4 | a new glob read passes CI | guard fails it | — |

---

## 5. Risks / open questions

- **Backfill correctness (Phase 1/2):** ingesting existing YAML into the DB must be idempotent and lossless. Snapshot counts before/after; dry-run diff. Highest-risk step.
- **Ledger history loss (Phase 2):** if any historical entries exist only in `ledger.md`, removing the merge before backfill loses them. Backfill must precede merge removal.
- **Dashboard parity (Phase 3):** the dashboard reads frontmatter + report bodies; report *bodies* may be file-only artifacts even after handoff metadata moves to DB. Decide whether bodies live in `handoffs.content`/`metadata` or stay as referenced files.
- **Agent round-submission bridge:** `discussions_dao.register_yaml_submission` (YAML→DB ingest of agent round files) is intentional and stays — agents write round YAML, the engine ingests it. Don't remove it; just ensure readers read the DB, not the round files.
- **`agents/*.status.yaml`:** no SQLite table exists for agent liveness/budget. Out of scope — leave YAML-backed, or add a table in a separate plan if desired.
- **`handoffs_dao.append` was effectively dead** — re-activating it may surface latent assumptions (e.g. `observation_capture` reads `get_latest` and currently gets nothing). Re-test those consumers once the table is live.

---

## 6. Scope & sequencing reality

- ~19 reader sites + 3 writer paths + ~4 dead-code removals across ~10 files.
- This is **not** a one-session task. Phases 0→4 are the natural commit boundaries; each is a separate PR.
- Per the project scope rule (>3 criteria / >4 files → decompose), every phase decomposes into the subtasks listed; Phase 1 and Phase 3 should each be split further (3a/3b/3c/3d are already separate).

---

## 7. Recommended order

**Phase 0 first** (safe deletions, immediate de-risk), **then Phase 1** (the keystone — nothing else is correct until handoffs are actually in SQLite), then 2, then 3a→3d, then 4. Do not start Phase 3 reader migration before Phases 1–2 — repointing a reader at an empty table is worse than the current glob.

---

## 8. Relationship to negative-knowledge retention

The earlier `PLAN-negative-knowledge-retention.md` becomes mostly **free** once this refactor lands:
- Phase 1 gives recall a real `handoffs` table + search API.
- Phase 3b/3c make recall read SQLite (including `decisions.alternatives` and `failures` via the same DAO wiring).
- The only net-new work left for negative knowledge is the *capture* nudge (write a `decisions` row with `alternatives` at report time). Fold that in as a Phase 3 add-on rather than a separate effort.

---

## 9. Advice (for the operator)

- **Ship Phase 0 today, separately.** Deleting confirmed-dead code (`handoffs_fts`, `yaml_sync_queue`, stubs, unreachable lines) is zero-risk, shrinks the surface, and makes the real work legible. It also stops the misconfigured FTS table from misleading the next person (it declares non-existent columns — a trap).
- **Treat Phase 1 as the whole game.** Everything downstream is mechanical once handoffs genuinely live in SQLite. If you only do Phases 0–1, you've fixed the actual lie in the doctrine; the reader migration can follow opportunistically.
- **Backfill before you delete any read path.** The one way this refactor loses data is removing a YAML reader before its data is in the DB. Order is non-negotiable: write path → backfill → reader migration → remove old reader.
- **Don't reintroduce FTS yet.** `handoffs_fts` rotted because it was added before a search path used it — and it was even misconfigured against the schema. Use `LIKE` at current volume; add FTS later, deliberately, with sync triggers and columns that match the table.
- **The deeper win is honesty.** Right now `sqlite_only.py` asserts something untrue. After Phase 4, the code and the doctrine agree, and a guard keeps them agreeing. That consistency is worth more than any single feature — it removes a class of "I assumed recall sees live state" bugs for every future contributor.
- **One caution on ambition:** this is a multi-PR refactor touching the dashboard and MCP tools. Given limited weekly bandwidth, resist doing it all at once. Phase 0 + Phase 1 is a coherent, valuable stopping point; bank it before committing to the long tail.
