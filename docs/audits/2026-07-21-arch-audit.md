# Architecture Audit — superharness
**Date:** 2026-07-21
**Scope:** broad, spot-checked (condensed pass within a larger `/portfolio-ready` run — schema, coupling, error-handling, and config-drift categories verified with evidence; deployment/observability/operational categories spot-checked only)
**Auditor:** Claude (arch-audit, condensed)

## Summary
The data layer is in noticeably better shape than the codebase's own recent history suggests: FK integrity (a previously-documented gap, PR #55/migration v33) is fully resolved — 11/11 foreign keys declare explicit `ON DELETE` behavior, verified directly against `db.py`, not assumed from memory. The DB-path divergence bug between CLI and MCP session code (also previously documented) is likewise resolved — both resolve through the single canonical `utils/paths.py`. The system's main structural risk is unchanged from prior audits: one 4,721-line god-module (`inbox_watch.py`) carries the watcher, dispatch, ledger, loop-guard, and staleness-detection logic together, and this session found two real NameError bugs inside it that had never been exercised by any test. Migration story is solid (35 versioned migrations, each auto-backed-up before applying). Concurrency test coverage is thin (3 files) relative to the amount of SQLite-writer code.

## CRITICAL — fix before next deploy
None found this pass. (The two NameError bugs found in `inbox_watch.py` this session were fixed with TDD as part of Stage 5 — see the main portfolio-ready report, not repeated here.)

## HIGH — fix before scale
- **God-module `inbox_watch.py` is 4,721 lines** with no internal module boundaries — watcher loop, dispatch, ledger writes, tool-loop guardrails, and log-staleness detection all live in one file. This session's `_ledger_record2` bug (a local-import alias defined in one function, called from a different function 1,357 lines away) is a direct symptom: the file is too large to visually verify that a name is in scope at a given call site. `docs/PLAN-coding-practices.md` (gitignored, referenced in HANDOFF) already identifies this and sets a ratchet ceiling at the current size — the plan exists, execution (iterations 6-9) is still open. Recommended: continue that plan rather than starting a new one.
  - Evidence: `wc -l src/superharness/commands/inbox_watch.py` = 4721; bug at `inbox_watch.py:2968` vs its correct import pattern at `inbox_watch.py:1611`.
- **Concurrency test coverage is thin relative to write surface.** Only 3 files match `*concurrent*`/`*chaos*` naming, against a DB layer where multiple processes (watcher, CLI, MCP server, dashboard) all write to the same SQLite file. HANDOFF references "concurrent-writer chaos tests (claim_next race + 8-thread contention)" from v1.80.2 — that coverage exists but is narrow (one specific race, not a general pattern applied across the DAO layer).
  - Evidence: `find tests -iname "*concurrent*" -o -iname "*chaos*"` → 3 files.

## MEDIUM — recoverable technical debt
- **Regression-test discoverability gap** (also surfaced in Stage 5/qa_coverage): 389 `fix`/`bug` CHANGELOG entries, zero tests tagged `@pytest.mark.regression` or living in `tests/regression/`. Protection likely exists scattered across `unit/`/`e2e/` but isn't discoverable as "regression coverage" without reading history.
- **`tests/contract/` name collision with the term "contract test."** This project's own domain concept (`contract.yaml`/task contract) shares a name with the standard testing term for external-API schema validation. 140 real tests live there testing internal DB/schema invariants — valuable, just potentially confusing to a contributor expecting Pact/OpenAPI-style tests.
- **No dedicated `docs/architecture.md` or `docs/spec.md`** — `docs/ARCHITECTURE.md` exists (confirmed linked from README) but wasn't read in full this pass given time constraints; recommend a follow-up pass specifically verifying it against current SQLite-only reality (the README itself needed a "SQLite reality" reconciliation as recently as PR #52, 2026-07-19 — worth confirming ARCHITECTURE.md didn't drift the same way).

## LOW — nice-to-have polish
- 4 bare `except:` clauses (no exception type) found via `git grep -c "except:"` — low count for 60k lines, but each is worth a specific type annotation.
- `docs/audits/` and `docs/AUDIT-*.md`/`docs/PLAN-*.md` naming isn't fully consistent (some audits live in `docs/audits/<date>-<name>.md`, some as `docs/AUDIT-<name>.md` at the docs root) — cosmetic, not investigated further.

## Out of scope this pass
Deployment provenance (version endpoint exists — `cmd_version` in `cli.py:618` — not deeply verified), observability/structured-logging consistency (spot-checked only, not systematically audited), operational runbooks (backup/rotation procedures not reviewed), full `docs/ARCHITECTURE.md` content review. This was a condensed pass inside a larger multi-stage audit (`/portfolio-ready`), not a standalone deep arch-audit — flagged explicitly per this command's own "cite evidence, never assume" discipline rather than silently skipping.

## Recommended next iterations
1. Resume `docs/PLAN-coding-practices.md` iterations 6-9 (already scoped, already has a ratchet in place) — this is the actual fix for the god-module risk that produced today's two real bugs.
2. Decide the regression-test tagging convention (adopt `@pytest.mark.regression` going forward at minimum — retagging 389 historical fixes is not realistic).
3. Verify `docs/ARCHITECTURE.md` against current SQLite-only reality — same class of drift the README needed fixing for in PR #52.
4. Expand concurrent-writer test coverage beyond the single `claim_next` race already covered, given how many processes write to the same SQLite file.
