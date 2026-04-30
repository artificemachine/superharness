# Morpheme + Superharness — improvement roadmap

**Date:** 2026-04-30
**Triggered by:** post-release audit of morpheme v0.9.0 and superharness v1.44.8
**Status:** approved scope, all 7 top recommendations

---

## Context

Both projects just shipped: **morpheme v0.9.0** (PR #34 bumps the pin to `superharness>=1.44.8`) and **superharness v1.44.8** (closes the last sqlite_only migration gaps). With releases out, this is the right moment to consolidate before the next feature batch.

Two parallel audits surfaced a clear pattern: the v1.43 SQLite migration in superharness was structurally incomplete and the patches in v1.44.5–1.44.8 cleaned up *known* call sites but did not finish the job. The dashboard, parts of the test suite, and several `is_sqlite_only()` branches still assume YAML semantics. On the morpheme side, the watcher rewire is technically sound but operationally opaque: when shux fails, users silently fall into demo mode with no signal.

The work below tackles the issues that:
- **(a)** prevent silent data loss
- **(b)** restore signal to the user and the test suite
- **(c)** unblock further cleanup

Lower-priority polish is listed but deferred.

---

## Top recommendations

### 1. Superharness: make migrations idempotent + safer (CRITICAL)

`_migration_v2` and `_migration_v3` use bare `ALTER TABLE … ADD COLUMN`. Re-running on a partially-migrated DB (crash recovery, manual restore) raises `duplicate column`. Combined with no pre-migration backup, this is a real data-corruption risk on real projects.

**Files:**
- `src/superharness/engine/db.py` (`_migration_v2`, `_migration_v3`, `_run_migrations`)
- `tests/unit/db/test_migration.py` (new — recovery-from-crash test)

**Change:**
- Wrap each `ADD COLUMN` in `try/except sqlite3.OperationalError` or pre-check via `PRAGMA table_info` (idempotent guard pattern).
- Pre-migration: copy `state.sqlite3` to `state.sqlite3.bak.<version>` inside the migration runner, before any DDL.
- Wrap each migration in a savepoint with explicit rollback on FK-constraint failure.
- Add an integration test: simulate v2 partial-apply, then run init and assert clean state.

**Verification:** `pytest tests/unit/db/test_migration.py` and a manual reproduction (apply v2 partially, kill, retry).

---

### 2. Superharness: triage and fix the 371 broken tests (HIGH)

A red CI suite hides real regressions. The audit categorized failures roughly as:
- ~45% obsolete (testing removed functionality)
- ~35% split-brain (fixture seeds YAML, prod reads SQLite)
- ~15% real bugs (zombie reconcile, watcher auto-gc)
- ~5% environmental

The test suite is the only thing standing between us and the next silent migration bug.

**Approach (one PR per group, not one mega-PR):**

| Group | Files | Action |
|---|---|---|
| Obsolete | `tests/unit/test_parallel_checkout_safety.py` | Delete entirely (functionality removed in v1.43; was kept on `@_legacy_skip` as a stop-gap). |
| Split-brain | `test_test_type.py`, `test_task_workflow_v2_phase1.py`, `test_task_failed_reason.py` | Apply the fixture pattern from PR #165's `test_verify_and_close.py`: seed SQLite alongside YAML, assert against SQLite. |
| Real bugs | `test_zombie_reconcile.py`, `test_watcher_auto_gc.py`, `test_watch_poll_cycle.py` | Reconcilers and `inbox_watch` still read `inbox.yaml` (tombstone). Migrate the prod paths to `inbox_dao`, then re-enable tests. |

**Files (prod):**
- `src/superharness/engine/zombie_reconcile.py`
- `src/superharness/engine/watcher_gc.py`
- `src/superharness/commands/inbox_watch.py` (or wherever `inbox.yaml` is still read)

**Verification:** `pytest tests/unit/ -q` returns 0 failures. Lock in by promoting `pytest -q` to a required CI gate (currently fail-open per the audit pattern).

---

### 3. Superharness: dashboard YAML reads → SQLite (HIGH)

`scripts/dashboard-ui.py` has 32 surviving `yaml.safe_load()` calls. v1.44.2 claimed the dashboard was migrated, but only the API layer was — the HTML renderer still reads tombstones. This is the single largest blocker for deleting the YAML tombstones, and it explains the "ghost data" reports where dashboard and `shux contract` disagree.

**Files:**
- `src/superharness/scripts/dashboard-ui.py` (32 call sites)
- `src/superharness/engine/state_reader.py` (gaps to fill if dashboard needs new aggregations)

**Change:** replace each `yaml.safe_load(open(...))` with the equivalent `state_reader` call. Add aggregation helpers in `state_reader` if a 1:1 mapping doesn't exist. After the migration, delete the tombstone YAMLs from `shux init` template.

**Verification:** smoke-load the dashboard against a fresh project and an existing project with tombstone files; diff the rendered HTML — should be identical except for "stale YAML" warnings disappearing.

---

### 4. Morpheme: make demo-mode and poller failures visible (HIGH)

When `shux adapter-payload` fails (wrong version, broken DB, daemon down), the watcher silently falls into demo mode and the user sees fake data. We hit exactly this scenario: daemon was dead for 83h and morpheme rendered demo tasks the whole time. Combined with a swallowed `catch {}` in `poller.js`, the user has zero signal that anything is wrong.

**Files:**
- `src/server/watcher.js` (~line 47, first `shux adapter-payload` call)
- `src/server/poller.js` (line ~17, `catch {}`)
- `src/views/CanvasView.vue` (header / EmptyState — render badge)
- `src/server/serve.js` (new `GET /health` endpoint)

**Change:**
- Add `errorCount`, `lastErrorAt`, `lastErrorMessage` to the poller; expose in payload.
- At first poll, run `shux --version`; if `<1.44.8` or call fails, surface as `mode: 'degraded'` with reason.
- Render a "DEMO MODE" / "POLLER STALLED" badge in the canvas header when `mode !== 'live'`.
- Add `GET /health` returning `{ ok, watcher: {attached, errorCount}, cache: {size, age} }` for orchestrators.

**Verification:** stop `shux daemon`, kill the SQLite DB, downgrade shux — confirm the badge appears in each case. Add Playwright test that mocks `/api/dispatch-status` 503 and asserts the banner.

---

### 5. Superharness: daemon process lifecycle (HIGH)

The daemon's monitor is spawned as a Python `daemon=True` thread inside the CLI process — when the CLI exits, the monitor dies with it. The "daemon" only persists if the CLI is left running, which is not how anyone uses it. This is exactly the failure we hit (stale PID, watcher dead, autonomy broken).

**Files:**
- `src/superharness/commands/daemon.py` (lines ~99–180)
- `src/superharness/commands/doctor.py` (add daemon-health check)

**Change:**
- Fork the monitor as a real subprocess (`multiprocessing.Process` or `os.fork`/`os.execv` to detach).
- Write the *monitor* PID (not the launcher PID) to `daemon-state.json`.
- `shux daemon status` reads PID, checks alive via `os.kill(pid, 0)`; report dead PIDs explicitly.
- `shux doctor` adds: "daemon: alive (pid X) / DEAD since Y / never started" line.

**Verification:** `shux daemon start && exit` — PID survives. `kill -9 <pid>` — `shux daemon status` reports dead. `shux doctor` flags it.

---

### 6. Morpheme: README + docs drift (MEDIUM, easy)

README says "69 unit tests, 115 e2e tests"; reality is 149 + 11 spec files. `docs/features.md`, `docs/synod-integration.md`, etc. reference v0.6.0–v0.7.0 architecture without dated headers. Cheap to fix, high credibility cost while wrong.

**Files:**
- `README.md` (test counts + install instructions)
- `docs/features.md`, `docs/synod-integration.md`, `docs/CLAUDE_HANDOFF.md` (add "Last verified for v0.9.0" header; flag stale references)
- `package.json` `prepare` script: `vite build` → `npx vite build` so `npm install -g github:...` works without `npm pack`

**Verification:** `npm install -g github:artificemachine/morpheme` from a clean shell works without errors.

---

### 7. Superharness: kill the dead `else` branches (MEDIUM, low risk)

`is_sqlite_only()` always returns True since v1.43, but ~5 files still have `if is_sqlite_only(): … else: # YAML fallback`. The `else` branches are dead code that confuses maintainers and pulls future debugging into the wrong direction.

**Files (audit-identified):**
- `src/superharness/engine/lifecycle_rules.py`
- `src/superharness/engine/state_writer.py` (PR #165 already fixed `upsert_handoff` — finish the job for `set_task_status` and `set_inbox_status`)
- `src/superharness/engine/review_escalation.py`
- `src/superharness/engine/contract_io.py`
- one more (needs grep)

**Change:** delete `else:` branches; remove `is_sqlite_only` import where it becomes the only call. Keep one functional definition of `is_sqlite_only()` for now (don't remove the function — feature flag for any future YAML reintroduction).

**Verification:** existing tests pass. Manual grep: `rg "is_sqlite_only" src/` should drop by ~half.

---

## Deferred (do after the top 7)

### Morpheme
- Adapter-synod: archive to `docs/examples/`, remove watcher import.
- Split `TaskView.vue` (1706 lines) into `RunTelemetry`, `HandoffTimeline`, `ActionBar` sub-components.
- Lazy-load `CanvasView` route to shrink initial bundle (348KB → ~80KB).
- Validate `/api/discuss` subcommand input (string-split is currently lenient; not exploitable today, but tighten the regex).
- Request logging in `src/server/serve.js`.
- Keyboard accessibility on `DemoTour.vue`.

### Superharness
- Adapter-payload in-process cache (10s TTL with file-watcher invalidation) — defer until #4 lands and we measure real call rate from morpheme.
- Pydantic strict mode (`extra='forbid'`) — risky without a full schema review; defer until tests are green (#2).
- Tombstone YAML deletion + `shux export-yaml` audit-trail command — blocked on #3.
- CLI surface bloat: audit `install_wrapper.py`, `notify_desktop.py`, `heartbeat.py`, `pack.py`, `enhance.py`, `explain.py` for callers; move unused to `_experimental/`.
- Architecture doc: 1–2 page summary of the v1.43 SQLite-only model, linked from README.

---

## PR sequence (confirmed scope: all 7)

1. Superharness `#1` — migration idempotency + backup
2. Superharness `#2-A` — delete `test_parallel_checkout_safety.py`
3. Superharness `#5` — daemon lifecycle as detached subprocess
4. Morpheme `#4` — demo-mode badge + poller error surface + `/health` endpoint + version check
5. Superharness `#2-B` — split-brain test fixtures (re-use the `_setup_project` SQLite-seeding pattern from PR #165's `test_verify_and_close.py`)
6. Superharness `#2-C` — real bugs in zombie reconcile, watcher auto-gc, watch_poll_cycle prod paths + tests
7. Superharness `#3` — dashboard YAML reads → SQLite via `state_reader`
8. Morpheme `#6` + Superharness `#7` — cleanup pass: README + docs drift, `prepare` script fix, dead `else` branches

Stop and reconfirm with the user after PR #5 (mid-point) to decide whether to keep going or pause.

Each PR follows the same shape:
- Feature branch off `main` (`fix/...` or `chore/...`).
- TDD cycle: RED test → GREEN minimal fix → REFACTOR.
- CHANGELOG entry in the same commit.
- Patch version bump.
- Wait for explicit approval before merging.

---

## Why these and not others

The audit surfaced ~30 individual items. The 7 above were chosen because:

1. **They prevent silent failures.** Items #1, #4, #5 directly address paths where a real bug renders no error message. Silent failures are the most expensive class of bug.
2. **They restore feedback loops.** A green CI suite (#2) and a coherent dashboard (#3) make the next round of work safer.
3. **They unblock the next phase.** Tombstone YAML deletion needs #3. Schema-strict Pydantic needs #2. Adapter-payload caching needs the visibility from #4.
4. **They are well-scoped.** Each fits in a single focused PR with TDD coverage.

Items deferred either depend on one of the above, or are polish that can wait without compounding cost.
