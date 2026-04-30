# Improvement roadmap — TDD plans per PR

**Companion to:** `docs/improvement-roadmap.md`
**Cycle:** RED → GREEN → REFACTOR for each PR
**Cadence:** one PR at a time, patch version bump per PR, CHANGELOG entry inside the same commit, explicit owner approval before merge.

---

## PR #1 — Superharness: migration idempotency + backup

**Branch:** `fix/migration-idempotency`
**Bumps:** patch → `1.44.9`
**Acceptance:** running `init_db` on an already-migrated DB is a no-op; partial migrations recover; a backup exists for every version increment.

### RED — failing tests

Add `tests/unit/db/test_migration_idempotency.py`:

1. **`test_init_db_is_idempotent`**
   - Open new DB, call `init_db(conn)` twice in a row.
   - Currently fails with `sqlite3.OperationalError: duplicate column name: parent_id` on second call.
   - Assertion: second call returns without exception.

2. **`test_partial_v3_recovers`**
   - Open DB at `user_version=2`, manually run `ALTER TABLE tasks ADD COLUMN verified INTEGER NOT NULL DEFAULT 0` (simulate crash mid-migration).
   - Call `init_db(conn)`.
   - Currently fails with duplicate-column error on the simulated column.
   - Assertion: `init_db` completes; `PRAGMA user_version` returns 3; `verified_at` and `verified_by` columns exist.

3. **`test_migration_creates_backup`**
   - Open DB at `user_version=1`, populate one task row.
   - Call `init_db(conn)`.
   - Assertion: `state.sqlite3.bak.v1` and `state.sqlite3.bak.v2` exist next to `state.sqlite3` and contain the pre-migration data.

4. **`test_fk_violation_rolls_back`**
   - Stub `_migration_v3` to raise mid-DDL after the first ALTER.
   - Assertion: `user_version` stays at 2; the first ALTER is not persisted (savepoint rollback).

### GREEN — minimal fix

In `src/superharness/engine/db.py`:

```python
def _column_exists(conn, table, column) -> bool:
    return any(r["name"] == column for r in conn.execute(f"PRAGMA table_info({table})"))

def _add_column_if_missing(conn, table, column, ddl_clause):
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_clause}")

def _backup_db(project_dir, version):
    src = os.path.join(project_dir, ".superharness", "state.sqlite3")
    dst = f"{src}.bak.v{version}"
    if os.path.isfile(src) and not os.path.isfile(dst):
        shutil.copy2(src, dst)
```

Refactor `_run_migrations`:
```python
def _run_migrations(conn, current_version, project_dir):
    for v in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
        _backup_db(project_dir, current_version)
        with transaction(conn):
            conn.execute(f"SAVEPOINT migrate_v{v}")
            try:
                _MIGRATIONS[v - 1](conn)
                conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", (v, now_iso()))
                conn.execute(f"PRAGMA user_version = {v}")
                conn.execute(f"RELEASE SAVEPOINT migrate_v{v}")
            except Exception:
                conn.execute(f"ROLLBACK TO SAVEPOINT migrate_v{v}")
                raise
```

Rewrite `_migration_v2` and `_migration_v3` to use `_add_column_if_missing`. Update `init_db` signature to thread `project_dir` through.

### REFACTOR

- Move `_column_exists`, `_add_column_if_missing`, `_backup_db` into a small `migrations.py` module if they grow.
- Extract `_run_single_migration(conn, v)` for clarity.

### CHANGELOG

```
- 2026-04-30 (v1.44.9): fix(db): idempotent migrations + automatic pre-migration backups. ALTER TABLE ADD COLUMN now guarded by PRAGMA table_info; each migration runs inside a SAVEPOINT with rollback on failure; state.sqlite3.bak.vN written before each schema bump. Recovery from partial migration verified.
```

---

## PR #2-A — Superharness: delete `test_parallel_checkout_safety.py`

**Branch:** `chore/drop-obsolete-checkout-safety-test`
**Bumps:** patch → `1.44.10`
**Acceptance:** test file removed, suite still collects, no skipped imports referencing `claim`/`launch`/`next_pending`.

### RED

Not a behavioural change — this is a deletion. The "RED" step is a documentation entry: confirm via `rg "test_parallel_checkout_safety|@_legacy_skip" tests/ src/` that no other module imports from the file or relies on the legacy fixtures.

### GREEN

```bash
git rm tests/unit/test_parallel_checkout_safety.py
```

If `_legacy_skip` is a shared decorator, leave the decorator definition but remove the import from the deleted file. If it was unique to this file, remove it as well.

### REFACTOR

- Search for `claim`, `launch`, `next_pending` symbols in `src/`. Any survivors are dead code from the v1.42 inbox API. Open a follow-up issue (do not include in this PR).

### CHANGELOG

```
- 2026-04-30 (v1.44.10): chore(tests): delete test_parallel_checkout_safety.py — tests v1.42 inbox primitives (claim, launch, next_pending) removed in v1.43; was kept on @_legacy_skip as a stop-gap. Suite collection improves.
```

---

## PR #5 — Superharness: daemon process lifecycle

**Branch:** `fix/daemon-detached-monitor`
**Bumps:** minor → `1.45.0` (behavioural change to daemon)
**Acceptance:** `shux daemon start && exit` leaves an alive monitor PID; `shux daemon status` and `shux doctor` report dead PIDs accurately.

### RED — failing tests

Add `tests/unit/daemon/test_daemon_lifecycle.py`:

1. **`test_daemon_survives_parent_exit`**
   - Run `shux daemon start --project <tmp>` in a subprocess; wait for it to exit.
   - Read PID from `<tmp>/.superharness/daemon-state.json`.
   - Assertion: `os.kill(pid, 0)` does not raise (process alive).
   - Currently fails because the monitor is a thread of the now-exited CLI process.

2. **`test_daemon_status_detects_dead_pid`**
   - Start daemon, capture PID, `os.kill(pid, signal.SIGKILL)`.
   - Run `shux daemon status --project <tmp>`.
   - Assertion: stdout contains "DEAD" or non-zero exit code; structured JSON with `--json` shows `alive: false`.

3. **`test_doctor_flags_dead_daemon`**
   - Same setup as #2.
   - Run `shux doctor --project <tmp>`.
   - Assertion: stdout contains a daemon-health line; exit code is 1 (warnings) or annotated finding present.

4. **`test_daemon_state_records_started_at`**
   - Start daemon, read state file.
   - Assertion: `started_at` is ISO 8601, within 5 seconds of now.

5. **`test_daemon_start_is_idempotent_when_alive`**
   - Start daemon, run start again.
   - Assertion: second start exits 0, prints "already running (pid X)", does not spawn a duplicate process.

### GREEN — minimal fix

In `src/superharness/commands/daemon.py`:

- Replace the `threading.Thread(daemon=True)` monitor with `multiprocessing.Process` plus an explicit double-fork (or `os.fork`/`os.execv`/`os.setsid`) so the monitor detaches from the launcher.
- After spawn, parent reads child PID, writes `{ pid, started_at, hostname }` to `daemon-state.json`, then exits.
- `shux daemon status` reads the JSON, calls `os.kill(pid, 0)`, formats output.
- `shux doctor`: add a check `_check_daemon_alive(project_dir)` that reads the state file and reports.

### REFACTOR

- Extract `_pid_alive(pid: int) -> bool` helper, share between `daemon.py` and `doctor.py`.
- Move state-file shape into `engine/daemon_state.py` with a typed dataclass.
- Document the lifecycle in a comment block at the top of `daemon.py`.

### CHANGELOG

```
- 2026-04-30 (v1.45.0): fix(daemon): monitor now runs as a detached subprocess and survives CLI exit. Previously spawned as a daemon thread that died with the launcher, leaving a stale PID and a dead watcher. shux daemon status and shux doctor now read the recorded monitor PID and report alive/dead accurately.
```

---

## PR #4 — Morpheme: demo-mode + poller failures visible

**Branch:** `fix/visibility-demo-mode-and-poller`
**Bumps:** minor → `0.10.0` (new endpoint, new payload field, new UI badge)
**Acceptance:** every failure mode (degraded shux version, dead daemon, broken adapter, network error) produces a visible signal in the UI within one poll cycle.

### RED — failing tests

Add `test/poller.test.js` (extend existing):

1. **`it("increments errorCount on fetch reject")`**
   - Wire a poller with `fetch: () => Promise.reject(new Error("boom"))`.
   - Tick the timer twice.
   - Assertion: `poller.state.errorCount === 2`, `poller.state.lastErrorMessage === "boom"`.
   - Currently fails because `poller.js` swallows in `catch {}`.

2. **`it("emits status: degraded when shux version below pin")`**
   - Stub `child_process.execFileSync('shux', ['--version'])` to return `superharness, version 1.43.0`.
   - Call `assessSourceMode({ shuxVersion, pin: '>=1.44.8' })`.
   - Assertion: `{ mode: 'degraded', reason: 'shux version below pinned minimum' }`.

3. **`it("falls back to demo only after poller logs error")`**
   - Tick poller, fetch rejects, count error.
   - Assertion: payload has `mode: 'degraded'` not `mode: 'live'`.

Add `test/api.test.js` (or extend):

4. **`it("GET /health returns 503 when poller stalled > 60s")`**
   - Stub poller state with `lastSuccessAt = now - 70_000`.
   - GET `/health`.
   - Assertion: status 503; body contains `{ ok: false, reason: 'poller_stalled' }`.

5. **`it("GET /health returns 200 with watcher metadata when healthy")`**
   - Healthy stub.
   - Assertion: status 200; body has `{ ok: true, watcher: { attached: true, errorCount: 0 }, cache: { size: <N>, age: <ms> } }`.

Add `tests/e2e/demo-mode-banner.spec.js` (Playwright):

6. **`renders DEMO MODE banner when /api/dispatch-status returns 503`**
   - Mock route `/api/dispatch-status` to 503.
   - Visit canvas.
   - Assertion: `page.getByText("DEMO MODE")` is visible.

7. **`renders POLLER STALLED banner with reason text`**
   - Mock payload with `mode: 'degraded', reason: 'shux exited 1'`.
   - Assertion: banner shows reason snippet.

### GREEN — minimal fix

`src/server/poller.js`:
```javascript
async function tick() {
  try {
    const data = await fetcher();
    state.errorCount = 0;
    state.lastSuccessAt = Date.now();
    onPayload(data);
  } catch (err) {
    state.errorCount += 1;
    state.lastErrorAt = Date.now();
    state.lastErrorMessage = String(err.message || err);
    if (state.errorCount === 1 || state.errorCount % 10 === 0) {
      console.warn(`[poller] ${state.errorCount} consecutive failures: ${state.lastErrorMessage}`);
    }
  }
}
```

`src/server/watcher.js`:
- On first attach, `execFileSync('shux', ['--version'])`; parse, compare to pin from `package.json` `engines.superharness`.
- Set `mode: 'live' | 'degraded' | 'demo'` and propagate through WebSocket payload.

`src/server/serve.js`:
- New route handler: `GET /health` returns the poller/cache state with appropriate status.

`src/views/CanvasView.vue`:
- New `<header class="status-banner">` slot, conditional on `mode !== 'live'`.

### REFACTOR

- Extract `assessSourceMode({ shuxVersion, pin, lastError })` from watcher.js into `src/server/sourceMode.js` with unit tests.
- Pull badge styling into a `StatusBanner.vue` component (CanvasView is already 1085 lines).

### CHANGELOG

```
- 2026-04-30 (v0.10.0): feat(visibility): demo-mode and poller failures now surface to the UI. Poller tracks errorCount/lastErrorAt/lastErrorMessage and exposes them in payload; watcher checks shux --version against the pinned minimum at attach time and emits mode='degraded' with reason when below pin or adapter fails. New GET /health endpoint returns 200 (live), 503 (poller stalled >60s), or 503 (degraded) with watcher and cache state. CanvasView shows a "DEMO MODE" / "POLLER STALLED" banner with reason text when mode != 'live'.
```

---

## PR #2-B — Superharness: split-brain test fixtures

**Branch:** `fix/split-brain-test-fixtures`
**Bumps:** patch → `1.45.1`
**Acceptance:** `test_test_type.py`, `test_task_workflow_v2_phase1.py`, `test_task_failed_reason.py` all green; suite-wide failure count drops by ~135.

### RED

Run each target file as-is and capture failures. The pattern is identical to PR #165 `test_verify_and_close.py`: fixture writes YAML but `read_contract` reads SQLite, so tasks are not found.

### GREEN

Build a shared helper `tests/helpers/seed.py`:

```python
def seed_project_sqlite(project: Path, tasks: list[dict]) -> None:
    """Seed SQLite alongside an existing YAML fixture so sqlite_only mode finds tasks."""
    from superharness.engine.db import get_connection, init_db, transaction
    from superharness.engine.contract_io import _task_row_from_dict
    from superharness.engine import tasks_dao
    conn = get_connection(str(project))
    init_db(conn)
    now = "2026-01-01T00:00:00Z"
    with transaction(conn):
        for t in tasks:
            tasks_dao.upsert(conn, _task_row_from_dict(t, str(project), now))
    conn.commit()
    conn.close()
```

In each target test file, call `seed_project_sqlite(project, tasks)` after writing `contract.yaml`. Update assertions to read SQLite via `tasks_dao.get` (mirror PR #165's `_get_task_sqlite` helper).

Promote `_get_task_sqlite` from `test_verify_and_close.py` into `tests/helpers/seed.py` so all three files share it.

### REFACTOR

- Audit other tests in `tests/unit/` for the same pattern; spot-fix obvious siblings.
- Add a `pytest.ini` marker `requires_sqlite_seed` so future contributors know which fixtures need this.

### CHANGELOG

```
- 2026-04-30 (v1.45.1): fix(tests): split-brain fixtures in test_test_type, test_task_workflow_v2_phase1, test_task_failed_reason — these wrote YAML but production reads SQLite (sqlite_only since v1.43). Added shared seed_project_sqlite helper; ~135 failing tests now green.
```

---

## PR #2-C — Superharness: real bugs in reconcilers

**Branch:** `fix/reconcilers-read-sqlite`
**Bumps:** patch → `1.45.2`
**Acceptance:** `test_zombie_reconcile.py`, `test_watcher_auto_gc.py`, `test_watch_poll_cycle.py` all green; the production reconcilers no longer silently miss zombies.

### RED

Run the three test files. The failures show real bugs: reconcilers and watcher GC still read `inbox.yaml` (tombstone) and therefore see zero items, so they never reconcile zombies or GC dead tasks.

Pin the smallest reproducer in each file. Where the test was wrong (asserting against YAML), rewrite to assert against `inbox_dao` state.

### GREEN

`src/superharness/engine/zombie_reconcile.py`, `src/superharness/engine/watcher_gc.py`, `src/superharness/commands/inbox_watch.py`:

- Replace `yaml.safe_load(open(inbox_file))` with `inbox_dao.get_all(conn)`.
- Replace `yaml.safe_dump` writes with `inbox_dao.upsert` / `inbox_dao.set_status`.

Concrete change pattern (do this once per file):
```python
# before
items = yaml.safe_load(open(inbox_file)) or []
for item in items:
    if item['status'] == 'launched' and not _pid_alive(item['pid']): ...

# after
from superharness.engine import inbox_dao
from superharness.engine.db import get_connection
conn = get_connection(project_dir)
items = inbox_dao.get_all(conn, status='launched')
for item in items:
    if not _pid_alive(item.pid): ...
```

### REFACTOR

- Where multiple files now open the same connection, hoist into a context manager `with open_state(project_dir) as conn`.
- Delete dead YAML helpers (`_load_inbox_yaml`, etc.) that no production caller uses anymore.

### CHANGELOG

```
- 2026-04-30 (v1.45.2): fix(reconcilers): zombie_reconcile, watcher_gc, and inbox_watch now read from SQLite (inbox_dao) instead of the inbox.yaml tombstone. Previously these silently saw zero items post-v1.43, so zombies were never reaped and dead tasks never GC'd. Tests for all three modules now green.
```

---

## PR #3 — Superharness: dashboard YAML reads → SQLite

**Branch:** `fix/dashboard-sqlite-only`
**Bumps:** minor → `1.46.0` (renderer behaviour change)
**Acceptance:** zero `yaml.safe_load` calls in `scripts/dashboard-ui.py`; dashboard renders identically against a project with no tombstone YAML files; tombstones can be deleted from `shux init` template.

### RED

Add `tests/unit/dashboard/test_dashboard_sqlite_only.py`:

1. **`test_dashboard_renders_without_tombstones`**
   - Build a project with `state.sqlite3` populated and **no** `contract.yaml`/`inbox.yaml`/`failures.yaml`/`decisions.yaml`/`ledger.md`.
   - Call the dashboard's HTML render entrypoint (or hit `/` via the in-process test client).
   - Assertion: 200 response; HTML contains task IDs from SQLite.
   - Currently fails because `yaml.safe_load(open(...))` raises `FileNotFoundError`.

2. **`test_dashboard_ignores_stale_yaml`**
   - Build a project with both: SQLite (current) and tombstone YAML (stale, different task).
   - Assertion: rendered HTML shows the SQLite task, not the YAML task.

3. **`test_no_yaml_safe_load_in_dashboard`** — static check.
   - Read `dashboard-ui.py` source.
   - Assertion: regex `yaml\.safe_load\b` returns zero matches.

### GREEN

Replace each `yaml.safe_load(open(...))` call with the equivalent `state_reader` API. Audit gaps:
- `state_reader.get_contract_doc` — already exists.
- `state_reader.get_inbox` — verify; if missing, add.
- `state_reader.get_failures` — likely missing; add.
- `state_reader.get_decisions` — likely missing; add.
- `state_reader.get_ledger_lines` — likely missing; add (read from `ledger` table).

Where the dashboard does an aggregation that doesn't map to a single `state_reader` call (e.g. count by status + group by owner), add it to `state_reader` as a typed function rather than open-coding SQL in the renderer.

After the refactor, remove `yaml` from `dashboard-ui.py` imports.

### REFACTOR

- Extract one render function per template section (`_render_contract_panel`, `_render_inbox_panel`, etc.) so each is independently testable.
- Add a deprecation note to the `shux init` template: "tombstone YAML files are no longer required — keep them for now for backward-compat with older shux clients reading the same project, planned removal in v1.50.0."

### CHANGELOG

```
- 2026-04-30 (v1.46.0): fix(dashboard): scripts/dashboard-ui.py now reads exclusively from SQLite via state_reader. 32 yaml.safe_load calls removed; dashboard renders correctly against projects with no tombstone YAML files. New state_reader helpers added: get_inbox, get_failures, get_decisions, get_ledger_lines. Tombstone YAML cleanup unblocked.
```

---

## PR #6+#7 — Cleanup pass

**Branches:**
- Morpheme: `chore/readme-and-prepare-fix`
- Superharness: `chore/remove-dead-yaml-branches`

**Bumps:** Morpheme patch → `0.10.1`; Superharness patch → `1.46.1`
**Acceptance:** README test counts match reality; `npm install -g github:...` works without `npm pack`; `rg "is_sqlite_only" src/superharness/` returns ~50% fewer hits with no test regression.

### RED — Morpheme #6

Add `test/readme.test.js` (smoke):

1. **`it("README test counts match the codebase")`**
   - Read `README.md`, parse a sentinel like `<!-- test-counts -->149 unit / 11 e2e`.
   - Run `vitest list` and `playwright test --list`; compare counts.
   - Assertion: counts match. Failing → README is stale.

(Optional: skip the smoke test and just keep README accurate manually. The smoke test is recommended because we already burned this once.)

For the `prepare` script fix, no test needed — the validation is a one-shot `npm install -g github:artificemachine/morpheme` from a clean shell.

### GREEN — Morpheme #6

- `README.md`: update test counts; clarify `npm pack` vs `npm install -g github:...`; mark sections with `<!-- test-counts -->` sentinels for the smoke test.
- `package.json`: `"prepare": "vite build"` → `"prepare": "npx vite build"`.
- `docs/features.md`, `docs/synod-integration.md`, `docs/CLAUDE_HANDOFF.md`: add `> Last verified for v0.9.0` header and date-stamp.

### RED — Superharness #7

For each file with a dead `else: # YAML fallback` branch:

1. **`test_no_yaml_branch_in_<module>`** (static check, one per file)
   - Parse the source via `ast`.
   - Assertion: no `If(test=Call(func=Name(id='is_sqlite_only')), orelse=[non-empty])` patterns.

OR (simpler): add one suite-wide static check `tests/unit/test_no_dead_yaml_branches.py` that runs the AST scan over `src/superharness/engine/` and asserts.

### GREEN — Superharness #7

- `src/superharness/engine/lifecycle_rules.py`: delete `else:` branch.
- `src/superharness/engine/state_writer.py`: delete remaining `else:` branches in `set_task_status` and `set_inbox_status`.
- `src/superharness/engine/review_escalation.py`: delete `else:`.
- `src/superharness/engine/contract_io.py`: delete `else:`.
- One more — confirmed via `rg "is_sqlite_only" src/superharness/engine/`.

Run unit suite (post-PR #2-A,B,C) — should be green.

### REFACTOR

- Where a function shrinks below 10 lines after dead-branch removal, consider inlining at its call site.
- Keep `is_sqlite_only()` itself for now as a feature flag.

### CHANGELOG (Morpheme)

```
- 2026-04-30 (v0.10.1): chore(docs): refresh README test counts (149 unit, 11 e2e specs); add "Last verified for v0.9.0" headers to docs/features.md, docs/synod-integration.md, docs/CLAUDE_HANDOFF.md; package.json prepare uses npx vite build so npm install -g github:... works without local npm pack.
```

### CHANGELOG (Superharness)

```
- 2026-04-30 (v1.46.1): chore(cleanup): remove dead `else:` branches in 5 engine modules (lifecycle_rules, state_writer, review_escalation, contract_io, +1) — these were YAML fallbacks that became unreachable when sqlite_only became default in v1.43. is_sqlite_only() retained as a feature-flag function. ~50% fewer call sites of is_sqlite_only across engine/.
```

---

## Mid-point checkpoint (after PR #5 of 8)

Stop and reconfirm with the user. Decide:
- Continue with PRs 6–8?
- Pause and stabilize?
- Re-prioritize based on findings during PRs 1–5?

Bring to the checkpoint:
- A diff summary across the four lands so far.
- Test-suite counts before/after.
- Any new findings from RED steps that uncovered additional hidden bugs.

---

## TDD discipline reminders

For every PR:
1. **Write the failing test first.** No production change before the test exists and fails for the expected reason. Capture the failure mode (assertion message + traceback) in the PR description.
2. **Make the smallest change to pass.** No drive-by refactors in the GREEN step.
3. **Refactor only after green.** With tests as a safety net, clean up duplication, naming, and structure.
4. **One logical change per PR.** Cross-cutting work belongs in a follow-up.
5. **CHANGELOG inside the same commit.** No "I'll catch up the changelog later" — that's how histories diverge.
6. **Wait for owner approval before merging.** Each PR is single-use; re-confirm even when the owner approved an earlier one in the same session.
