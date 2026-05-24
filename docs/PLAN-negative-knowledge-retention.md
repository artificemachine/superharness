# PLAN — Negative-Knowledge Retention (Option A: recall reads SQLite)

**Date:** 2026-05-22 (revised after FTS verification)
**Status:** proposed (iteration plan, not yet approved)
**Origin:** `~/DevOpsSec/docs/ARCH-memory-architecture-extractions-2026-05-22.md` (extraction B)
**Driver:** A memory that records only successes is a useless showcase. Failures, bad decisions, and abandoned approaches are the reusable knowledge that stops future sessions re-litigating dead ends.

---

## Verified findings (these ground the plan)

Inspected `src/superharness/engine/{db,recall,handoffs_dao,decisions_dao,failures_dao}.py`.

1. **Storage already exists.** `decisions` table has `decision`, `reason`, **`alternatives`**; `failures` table has `pattern`, `error_snippet`. Both have clean DAO read APIs (`get_recent()`). This was never a schema-gap problem.

2. **`recall` does not use SQLite for the knowledge tables.** `recall.py` is a keyword scanner that reads:
   - `.superharness/handoffs/*.{yaml,yml,md}` — **export files on disk**
   - the `tasks` SQLite table — titles/subtask-titles only
   - `.superharness/ledger.md` — a file
   It never queries the `handoffs`, `decisions`, or `failures` tables. So `decisions.alternatives` is invisible to recall regardless of whether it's populated.

3. **`handoffs_fts` is dead code.** Created by migration v6, referenced nowhere else — never populated, never queried. There is no FTS sync mechanism because there is no live FTS.

4. **Doctrine contradiction.** `superharness/CLAUDE.md`: *"State lives in SQLite — YAML files are DEAD … export-only artifacts."* Yet `recall` treats the export files as its primary search corpus. recall reads the artifact, not the source of truth.

**Reframe:** the cabinet exists (`decisions`/`failures`), but recall searches the wrong building (export files), and there's an empty filing system rusting in the basement (`handoffs_fts`). Fix all three together.

---

## Goal

`shux recall "<keywords>"` returns past **handoffs + rejected alternatives + failure traces**, sourced from SQLite (the actual source of truth), so dead ends surface before they're repeated — and the recall path stops contradicting the SQLite doctrine.

---

## Scope decomposition

Touches >4 files, so per the project scope rule it decomposes into ordered subtasks.

### Subtask 1 — recall reads SQLite knowledge tables (Option A core)
- **Files:** `src/superharness/engine/recall.py`, `decisions_dao.py`, `failures_dao.py`, `handoffs_dao.py`
- **RED:** test that `recall("<term that exists only in a decision's `alternatives` field>")` and `recall("<term in a failure `error_snippet`>")` return zero results today.
- **GREEN:**
  - Add a `search()`/`get_matching()` helper to `decisions_dao` and `failures_dao` (substring/`LIKE` over their text columns; `handoffs_dao` likely already supports history reads to filter).
  - Extend `recall.search()` to query these three DB tables and merge results, each tagged by source (`handoff` / `decision` / `failure`).
  - Keep multi-term OR logic and `--since` filtering consistent with current behavior.
- **REFACTOR:** one shared "match rows by terms + tag source" helper instead of three copies.
- **Done when:** RED tests pass; recall surfaces decision-`alternatives` and failure text, labeled by source.

### Subtask 2 — retire the file-scan + dead FTS (doctrine cleanup)
- **Files:** `recall.py`, `db.py` (new migration), tests
- **RED:** a test asserting recall returns identical results whether or not `.superharness/handoffs/*.yaml` export files are present (i.e. recall no longer *depends* on the files).
- **GREEN:**
  - Switch recall's handoff source from file-scan to the `handoffs` DB table (`handoffs_dao.get_history`/equivalent). Export files remain as exports; recall stops reading them.
  - Decide on `ledger.md`: if the ledger lives in the `ledger` table, switch recall to it too; if ledger is genuinely file-only, document it as the one sanctioned exception.
  - Add migration `_migration_v<N>`: `DROP TABLE IF EXISTS handoffs_fts` — remove the orphaned dead table. (We use `LIKE` queries now; FTS can be reintroduced deliberately if volume ever demands it — see advice.)
- **REFACTOR:** delete now-unused file-scan code paths in `recall.py`.
- **Done when:** recall is file-independent for handoffs; `handoffs_fts` is gone; the doctrine contradiction is closed.

### Subtask 3 — capture: force `alternatives` at report/close
- **Files:** `commands/task.py` and/or `close.py`, `decisions_dao.py`, handoff template docs
- **RED:** test that reporting/closing a task with a stated discarded approach currently leaves `decisions.alternatives` empty.
- **GREEN:**
  - On `report_ready`/close, if the report carries a `rejected:`/`alternatives:` block, write a `decisions` row via `decisions_dao.record()` with `alternatives` populated.
  - Document the `rejected:` block in the handoff-format reference.
  - Advisory only: if a multi-step task closes with zero decisions rows, emit a one-line nudge. **No hard gate** — closing stays friction-light.
- **Done when:** RED test passes; a report carrying a rejected block produces a searchable `decisions` row (visible via subtask 1's recall path).

---

## Dead-code & doctrine-cleanup strategy (explicit)

| Item | Problem | Action | Subtask |
|---|---|---|---|
| `handoffs_fts` | orphaned, never used | DROP via migration | 2 |
| recall file-scan of `handoffs/*.yaml` | reads export artifact, not source of truth | switch to `handoffs` DB table | 2 |
| recall `ledger.md` scan | possible file/SQLite split | reconcile to DB or document as sanctioned exception | 2 |
| `decisions`/`failures` unsearchable | DAOs exist but recall ignores them | wire into recall | 1 |

**Principle for this cleanup:** recall must read the **source of truth (SQLite)**, never the export artifacts. Export files keep being written for portability/dashboard/human diffing — they are outputs, not inputs. Any code path that *reads* an export file as authoritative is a bug to close, not a feature to preserve.

---

## TDD cycle summary

| Phase | What |
|---|---|
| RED | (a) recall misses decision/failure text; (b) recall depends on export files; (c) reports don't populate `alternatives` |
| GREEN | DB-backed recall (1) → file-independence + drop FTS (2) → capture-on-report (3) |
| REFACTOR | one shared row-match/source-tag helper; delete file-scan paths |

---

## Explicitly out of scope

- No new top-level table — `decisions`/`failures` already exist.
- No hard gate on task close (advisory nudge only).
- No reintroduction of FTS in this iteration — `LIKE` is sufficient at current volume.
- Active-forgetting / memory decay — parked (premature at current scale).
- Removing the export-file *writers* — they stay; only recall's *dependence* on them is removed.

---

## Risks / open questions

- **`ledger.md` source of truth:** confirm whether the ledger is mirrored to a `ledger` SQLite table or is genuinely file-only. Determines whether subtask 2 reconciles it or documents an exception.
- **Behavior parity:** the file-scan returns context snippets (`_ctx`) and date inference from filenames. DB-backed recall must preserve usable snippets + dates (use `created_at`, decision/failure text) so output quality doesn't regress.
- **`LIKE` performance:** fine at current volume; if recall ever feels slow, that's the deliberate trigger to reintroduce a properly-synced FTS (across handoffs+decisions+failures this time, with triggers).
- **Capture friction:** the report nudge is advisory; if noisy, drop it and rely on the template convention.

---

## Recommended order

1 → 2 → 3. Subtask 1 delivers value immediately (surfaces existing decisions/failures). Subtask 2 closes the doctrine contradiction and removes dead code. Subtask 3 improves capture quality going forward.

---

## Advice (for the operator)

- **Do subtask 1 alone first and stop to evaluate.** Wiring recall to read `decisions`/`failures` is the high-value, low-risk slice. It surfaces knowledge you may *already* have sitting in the DB unsearched — you might find subtask 3 (capture) matters less than expected if decisions are already being recorded, or much more if the table is empty. Let the data tell you.
- **Don't gold-plate with FTS now.** The dead `handoffs_fts` is a cautionary tale: an index was added before there was a search path to use it, and it rotted. `LIKE` over current volume is correct. Reintroduce FTS only when measured latency justifies it, and only with sync triggers so it can't silently drift again.
- **Treat the doctrine cleanup as the real prize.** The negative-knowledge feature is the occasion; the lasting win is recall reading the source of truth instead of export artifacts. That contradiction would have bitten any future feature that assumed recall sees live state. Closing it has leverage beyond this one task.
- **Keep capture frictionless.** The moment recording a rejected approach feels like a chore, it stops happening and the whole feature decays. Advisory nudge, never a gate.
