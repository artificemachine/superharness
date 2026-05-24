# Bulletproof Audit — SQLite is single source of truth (v3)

**Date:** 2026-05-24
**Focus:** "SQLite is single source of truth"
**Prior report:** bulletproof-report-2026-05-24-sqlite-sot-v2.md

## SCOPE

Python/shell project. Doctrine in `CLAUDE.md`, `AGENTS.md`, `engine/sqlite_only.py`, `docs/IMPLEMENTATION-status.md`.

## CLAIMS AUDITED

| # | Claim | Source | Verdict | Evidence |
|---|-------|--------|---------|----------|
| C1 | "contract.yaml, inbox.yaml, failures.yaml, decisions.yaml are DEAD" | CLAUDE.md:9, AGENTS.md:31 | VERIFIED | dashboard-ui.py `inbox_items()` routes to state_reader (SQLite). All other refs are path derivation, doc strings, or file-existence checks. Zero YAML reads of operational state. |
| C2 | "All operational state reads routed through DAOs / state_reader" | sqlite_only.py:3 | VERIFIED | discuss._find_pending_handoff → handoffs_dao (Layer 3). cmd_status → state_reader.get_handoffs(). delegate._get_latest_handoff_task → handoffs_dao.get_for_agent(). inbox_watch._find_pr_url → handoffs_dao.search(). inbox_dispatch YAML path in `_KNOWN_BLIND` + unreachable at runtime. |
| C3 | "YAML files never read as authoritative input" | sqlite_only.py:6, IMPLEMENTATION-status.md:3 | VERIFIED | All remaining safe_load calls read config (profile.yaml, schedule.yaml, workflow.yaml, heartbeat config, agent status signals). context.py:80 parses YAML text from a SQLite content column, not a file. inbox_dispatch else-branch unreachable when is_sqlite_only()=True. |
| C4 | "All YAML runtime read/write paths eliminated" | IMPLEMENTATION-status.md:60 | **VIOLATED** | `inbox_dispatch.py:731–750` — live subprocess-based inbox.yaml read path in `_claim_next_item` else-branch. Reachable when STATE_BACKEND=dual or state.sqlite3 absent. Code was *guarded*, not *eliminated*. |
| C5 | "ratchet guard BASELINE is empty" | sqlite_only.py:4 | VERIFIED | `tests/test_no_state_yaml_reads.py`: `BASELINE: set[str] = set()`. Confirmed. |
| C6 | "handoffs_fts is dead AND misconfigured" | PLAN doc:17 | VERIFIED | Created v6 with non-existent columns, dropped unconditionally in migration v23. Zero query sites. |
| C7 | "yaml_sync_queue should be dropped (dead/inert)" | PLAN doc:45 | **VIOLATED** | Created in migration (db.py:339–395). Zero operational queries. No DROP migration exists. |
| C8 | "yaml_sync.py deleted" | PLAN doc:45 | VERIFIED | File absent. Zero import sites. |

## HONESTY SCORE: 6/8 verified.

Two violations. Core SoT invariant holds in production; gaps are a live-but-unreachable compat path and a dead DB table never dropped.

## DRIFT-CLASS FINDINGS

**Dead code:**
- `context.py:24` — `_load_yaml_safe(path: Path)` defined, zero callers.

**Dead schema:**
- `yaml_sync_queue` table — created in migration, never INSERTed/SELECTed operationally. Not dropped.

**Silent-success risk:**
- `inbox_dispatch.py:731–750` — YAML fallback is "dead at runtime" only because state.sqlite3 exists. Absent/corrupted DB silently falls through to YAML read. No alarm fires.

**Unenforced invariants:**
- 8 direct `conn.execute("UPDATE inbox ...")` sites bypass inbox_dao: inbox_watch.py:1313,1568,1747,3550 and status.py:624,643,668,738.

## REMEDIATION

**C4 fix (pick one):**
- Delete `inbox_dispatch.py:731–750` (preferred — the YAML path cannot work; inbox.yaml no longer exists)
- OR replace else-branch with hard error instead of subprocess call

**C7 fix:**
- Add migration: `conn.execute("DROP TABLE IF EXISTS yaml_sync_queue")`

**Dead code:**
- Delete `context.py:24–30` (`_load_yaml_safe`)

## PROGRESS

| Claim | v2 (pre-Layer-3) | v3 (post-Layer-3) | Movement |
|-------|-----------------|-------------------|----------|
| C1 dead files | VERIFIED | VERIFIED | held |
| C2 all reads through DAOs | **VIOLATED** | VERIFIED | **FIXED** |
| C3 YAML never auth | **VIOLATED** | VERIFIED | **FIXED** |
| C4 paths eliminated | **VIOLATED** | VIOLATED | partial fix (approve OK, compat branch remains) |
| state_reader always SQLite | VERIFIED | VERIFIED | held |
| C8 yaml_sync.py deleted | VERIFIED | VERIFIED | held |
| C5 BASELINE empty | new | VERIFIED | new green |
| C6 handoffs_fts dead | new | VERIFIED | new green |
| C7 yaml_sync_queue | not probed | **VIOLATED** | newly exposed |

Net: 3 violations → 2 violations. Layer 3 closed the approve/read gaps. Two pre-existing issues newly visible.
