# Plan: SQLite Ledger Migration (Stable Task Storage) — v3

## Goal

Migrate the superharness state engine from concurrent YAML files to a single
transactional SQLite database with WAL mode.

Root cause being fixed: I/O race conditions and lock contention in a distributed
system using plain text files as primary state. The watcher, dispatcher, CLI,
and agents all mutate the same YAML files concurrently, producing stale reads,
partial writes, orphaned locks, and "frozen" processes.

After this migration:
- State transitions are ACID.
- Liveness is observable via SQL, not file mtime.
- Parallel agents cannot corrupt shared state.
- `WatcherHealthAdvisor` (phi4-mini) becomes redundant and is removed.
- `OrchestratorDispatchAdvisor` becomes optional (SQL query replaces routing brain).

## Non-goals

- Not changing the YAML format of handoff files at rest in other projects.
- Not migrating the profile/config YAMLs (`profile.yaml`, `watcher.yaml`, `harness.yaml`) — those are config, not state, and file-based is fine.
- Not a rewrite of the dispatch subprocess model (scope creep).

---

## Architecture

**Single DB file:** `.superharness/state.sqlite3`

- Replaces: `inbox.yaml`, `contract.yaml` (tasks block), `handoffs/*.yaml`,
  `failures.yaml`, `decisions.yaml`, `ledger.md`, `reviews.db`
- Does **not** replace: config YAMLs, worktree state, git state.

**WAL mode.** `PRAGMA journal_mode=WAL` set at connection time. Allows concurrent
reads during writes. Required minimum SQLite version: **3.35** (for
`UPDATE...RETURNING`). Pinned in runtime check at startup.

**Schema versioning.** `PRAGMA user_version` tracks schema version from day 1.
Every schema change ships with a forward migration function. Downgrade is not
supported (standard practice).

---

## Schema

### Versioning

```sql
PRAGMA user_version = 1;

CREATE TABLE schema_migrations (
  version     INTEGER PRIMARY KEY,
  applied_at  TEXT    NOT NULL
);
```

### Core tables

```sql
-- Tasks (replaces tasks block in contract.yaml)
CREATE TABLE tasks (
  id                   TEXT    PRIMARY KEY,
  title                TEXT    NOT NULL,
  owner                TEXT,
  status               TEXT    NOT NULL,  -- todo|plan_proposed|plan_approved|
                                          -- in_progress|report_ready|
                                          -- review_failed|done|cancelled
  effort               TEXT,              -- low|medium|high|xhigh|max
  project_path         TEXT,              -- absolute path
  development_method   TEXT,              -- tdd|bdd|ddd|none
  acceptance_criteria  TEXT,              -- JSON array
  test_types           TEXT,              -- JSON array
  out_of_scope         TEXT,              -- JSON array
  definition_of_done   TEXT,              -- JSON array
  context              TEXT,
  tdd                  TEXT,              -- JSON object {red, green, refactor}
  version              INTEGER NOT NULL DEFAULT 1,  -- optimistic concurrency
  created_at           TEXT    NOT NULL,
  plan_proposed_at     TEXT,
  plan_approved_at     TEXT,
  in_progress_at       TEXT,
  report_ready_at      TEXT,
  done_at              TEXT,
  cancelled_at         TEXT
);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_owner  ON tasks(owner);

-- Many-to-many task dependencies (replaces blocked_by string)
CREATE TABLE task_dependencies (
  dependent_task_id     TEXT NOT NULL,  -- this task is blocked
  prerequisite_task_id  TEXT NOT NULL,  -- ...by this task
  PRIMARY KEY (dependent_task_id, prerequisite_task_id),
  FOREIGN KEY (dependent_task_id)    REFERENCES tasks(id) ON DELETE CASCADE,
  FOREIGN KEY (prerequisite_task_id) REFERENCES tasks(id) ON DELETE RESTRICT
);
CREATE INDEX idx_deps_prereq ON task_dependencies(prerequisite_task_id);

-- Inbox (replaces inbox.yaml)
CREATE TABLE inbox (
  id              TEXT    PRIMARY KEY,
  task_id         TEXT    NOT NULL,
  target_agent    TEXT    NOT NULL,
  status          TEXT    NOT NULL,    -- pending|launched|running|paused|done|failed|stale
  priority        INTEGER NOT NULL DEFAULT 2,
  retry_count     INTEGER NOT NULL DEFAULT 0,
  max_retries     INTEGER NOT NULL DEFAULT 3,
  pid             INTEGER,
  project_path    TEXT,
  plan_only       INTEGER NOT NULL DEFAULT 0,
  failed_reason   TEXT,
  created_at      TEXT    NOT NULL,
  launched_at     TEXT,
  last_heartbeat  TEXT,
  paused_at       TEXT,
  failed_at       TEXT,
  done_at         TEXT,
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
CREATE INDEX idx_inbox_status_priority ON inbox(status, priority DESC, created_at);
CREATE INDEX idx_inbox_heartbeat       ON inbox(status, last_heartbeat);

-- Handoffs: row-per-event, preserves history across lifecycle cycles
CREATE TABLE handoffs (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id      TEXT    NOT NULL,
  phase        TEXT    NOT NULL,    -- plan|report|review
  status       TEXT    NOT NULL,    -- plan_proposed|plan_approved|report_ready|
                                    -- review_failed|review_approved
  from_agent   TEXT,
  to_agent     TEXT,
  content      TEXT,                -- raw YAML body
  metadata     TEXT,                -- JSON extras (PR URL, etc.)
  created_at   TEXT    NOT NULL,
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
CREATE INDEX idx_handoffs_task ON handoffs(task_id, created_at DESC);

-- Failures (replaces failures.yaml)
CREATE TABLE failures (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id        TEXT,
  agent          TEXT,
  pattern        TEXT,           -- auth_block|timeout|oom|parse_error|...
  error_snippet  TEXT,
  created_at     TEXT NOT NULL
);
CREATE INDEX idx_failures_task           ON failures(task_id);
CREATE INDEX idx_failures_agent_pattern  ON failures(agent, pattern);

-- Decisions (replaces decisions.yaml)
CREATE TABLE decisions (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  agent         TEXT,
  task_id       TEXT,
  decision      TEXT    NOT NULL,
  reason        TEXT,
  alternatives  TEXT,          -- JSON
  created_at    TEXT    NOT NULL
);
CREATE INDEX idx_decisions_agent_time ON decisions(agent, created_at);

-- Ledger (replaces ledger.md — operational trace)
CREATE TABLE ledger (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id     TEXT,
  agent       TEXT,
  action      TEXT NOT NULL,    -- dispatched|heartbeat|completed|paused|recovered
  details     TEXT,             -- JSON
  created_at  TEXT NOT NULL
);
CREATE INDEX idx_ledger_time ON ledger(created_at);
CREATE INDEX idx_ledger_task ON ledger(task_id, created_at);

-- Review store (absorbs src/superharness/harness/review_store.py DB)
CREATE TABLE review_store (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  owner       TEXT    NOT NULL,
  task_type   TEXT    NOT NULL DEFAULT '',
  duration_s  REAL    NOT NULL DEFAULT 0,
  score       REAL    NOT NULL DEFAULT 0,
  failed      INTEGER NOT NULL DEFAULT 0,
  recorded_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_review_owner_type ON review_store(owner, task_type);

-- Watcher singleton (prevents two watchers running concurrently)
CREATE TABLE watcher_instance (
  key             TEXT    PRIMARY KEY CHECK (key = 'singleton'),
  pid             INTEGER NOT NULL,
  hostname        TEXT,
  started_at      TEXT    NOT NULL,
  last_heartbeat  TEXT    NOT NULL
);

-- Parity queue (dual-write phase only; dropped at iteration 10)
CREATE TABLE yaml_sync_queue (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  op_type     TEXT    NOT NULL,   -- upsert_task|update_inbox|append_handoff|...
  payload     TEXT    NOT NULL,   -- JSON
  status      TEXT    NOT NULL DEFAULT 'pending',   -- pending|applied|failed
  attempts    INTEGER NOT NULL DEFAULT 0,
  last_error  TEXT,
  created_at  TEXT    NOT NULL,
  applied_at  TEXT
);
CREATE INDEX idx_yaml_sync_pending ON yaml_sync_queue(status, created_at);
```

### Concurrency model

- **Atomic task claim** (replaces dispatch lock):
  ```sql
  UPDATE inbox
  SET status='launched', pid=?, launched_at=?
  WHERE id = (
    SELECT id FROM inbox
    WHERE status='pending' AND target_agent=?
    ORDER BY priority DESC, created_at
    LIMIT 1
  )
  RETURNING *;
  ```
  Two watchers calling this simultaneously: SQLite serializes, only one gets the row.

- **Watcher singleton**:
  ```sql
  INSERT INTO watcher_instance (key, pid, hostname, started_at, last_heartbeat)
  VALUES ('singleton', ?, ?, ?, ?);
  ```
  Fails on UNIQUE. Takeover logic: if `last_heartbeat` older than threshold,
  `UPDATE ... WHERE last_heartbeat < ?` succeeds only if the incumbent is stale.

- **Task edit concurrency** (optimistic):
  ```sql
  UPDATE tasks
  SET owner=?, version=version+1, ...
  WHERE id=? AND version=?;
  ```
  Client passes the version it read. Mid-air collisions fail the update; caller
  retries with fresh read.

### Dual-write transaction model (iterations 4-8)

**SQLite is authoritative.** YAML is eventually consistent via `yaml_sync_queue`:

```
operation:
  1. BEGIN TRANSACTION
  2. Write to canonical table(s)
  3. INSERT INTO yaml_sync_queue (op_type, payload)
  4. COMMIT

background sync loop (every watcher tick):
  SELECT * FROM yaml_sync_queue WHERE status='pending' ORDER BY id LIMIT N
  For each row:
    try: write to YAML file(s)
         UPDATE status='applied', applied_at=?
    except:
         UPDATE status='failed', attempts=attempts+1, last_error=?
         (retry on next tick until max attempts, then surface in doctor)
```

Why this shape:
- SQLite commit is atomic — both state change and sync-queue entry succeed or neither does.
- YAML write failures do not block the authoritative state.
- Lag is observable (`COUNT(*) FROM yaml_sync_queue WHERE status='pending'`).
- Parity check (iter 5) reads YAML and compares to SQLite — detects silent drift.

---

## Iterations (TDD: RED → GREEN → REFACTOR)

### Iteration 1 — DB Init, WAL, Versioning Framework

**Goal:** Foundational DB connection + schema migration infrastructure.

- **RED** `tests/unit/db/test_init.py`:
  - DB file created at `.superharness/state.sqlite3`
  - All tables exist after `init_db()`
  - `PRAGMA journal_mode` returns `wal`
  - `PRAGMA user_version` returns `1`
  - `schema_migrations` has row for version 1
  - SQLite version check rejects <3.35 with clear error
- **GREEN** `src/superharness/engine/db.py`:
  - `get_connection(project_dir)` with WAL, FK enforcement, timeout
  - `init_db(conn)` idempotent
  - `run_migrations(conn)` walks `schema_migrations`, applies pending
- **REFACTOR:** Extract connection factory to `_ConnectionPool` with thread-local reuse.

### Iteration 2 — Migration Bridge

**Goal:** One command converts an existing project's YAML state to SQLite.
Idempotent, resumable, handles source + worker directories.

- **RED** `tests/unit/db/test_migration.py`:
  - Migration of clean project (inbox + contract + handoffs + failures + decisions): DB rows match YAML data 1:1
  - Running migration twice produces identical DB (idempotency)
  - Corrupt YAML in one file does not block migration of others (recorded to `ledger` as `migration_error`)
  - Orphaned handoff (task_id not in contract) recorded but not imported
  - Worker project at `~/.superharness-workers/<name>/.superharness/` also migrated
  - Existing `reviews.db` from phi4-mini harness merged into `review_store` table
  - Large-project perf: 10k-task fixture migrates in <10s
- **GREEN** `src/superharness/engine/migrate_yaml.py`:
  - `migrate_all_to_sqlite(project_dir)` parses each source file independently
  - Per-file try/except with error row to ledger
  - Upserts (not plain inserts) so re-running is idempotent
  - Detects and merges worker copy via symlink inspection
- **REFACTOR:** Extract per-source parsers (`_migrate_inbox`, `_migrate_contract`, ...) for readability.

### Iteration 3 — DAOs + Atomic Claim + Watcher Singleton

**Goal:** Python API for state operations. Atomic claim pattern. Singleton enforcement.

- **RED** `tests/unit/db/test_dao.py`:
  - `inbox_dao.enqueue(item)` round-trips
  - `inbox_dao.get_pending(target_agent)` orders by priority DESC, created_at
  - `inbox_dao.claim_next(target_agent, pid)` returns exactly one row under contention (simulated via threads)
  - `tasks_dao.update(task_id, version, changes)` fails on stale version
  - `handoffs_dao.append(task_id, phase, status, content)` preserves history across multiple rows
- **RED** `tests/unit/db/test_watcher_singleton.py`:
  - Two watchers start simultaneously: only one acquires singleton
  - Stale watcher (heartbeat > threshold): new watcher takes over atomically
- **GREEN:**
  - `src/superharness/engine/inbox_dao.py`
  - `src/superharness/engine/tasks_dao.py`
  - `src/superharness/engine/handoffs_dao.py`
  - `src/superharness/engine/watcher_singleton.py`
- **REFACTOR:** Shared `with transaction(conn):` context manager.

### Iteration 4 — Dual-Write Wiring (Watcher + Dispatcher)

**Goal:** Every write hits SQLite + enqueues YAML sync. YAML remains readable
and authoritative for this phase. SQLite shadows.

- **RED** `tests/unit/test_dual_write.py`:
  - `shux delegate` writes to inbox table AND inbox.yaml (eventual)
  - Writes to SQLite first, enqueues sync op, YAML catches up on next tick
  - SQLite failure aborts the op (YAML not written)
  - YAML sync failure leaves item in `yaml_sync_queue` status='failed'
- **GREEN:**
  - `src/superharness/commands/inbox_watch.py`: dual-write path behind `STATE_BACKEND=dual` flag
  - `src/superharness/commands/inbox_dispatch.py`: same
  - `src/superharness/engine/yaml_sync.py`: background sync loop, called from watcher tick
- **REFACTOR:** Write path centralized — only two functions (`write_inbox_op`, `write_task_op`) touch both backends.

### Iteration 5 — Parity Monitoring (NEW — gate iteration)

**Goal:** Detect silent drift between SQLite and YAML. Block later iterations
if drift persists.

- **RED** `tests/unit/test_parity.py`:
  - Identical state → drift count 0
  - Diverged state (manually mutated YAML) → drift detected, reported per table
  - Drift persists across ticks → status = unhealthy
  - Self-healing: if YAML drift, re-enqueue sync op and retry
- **GREEN:**
  - `src/superharness/engine/parity.py`: `check_parity(project_dir) -> ParityReport`
  - `shux doctor` shows drift counts
  - Watcher tick calls parity check every N cycles (configurable)
  - Drift > threshold → `ledger` entry with action=`parity_alert`
- **REFACTOR:** Parity check per-table (composable).

**Gate:** iterations 6-10 must not start until parity stays at 0 for 24h soak on real project.

### Iteration 6 — CLI Command Porting (Full Audit)

**Goal:** Every CLI command that reads/writes state uses dual-write path.

Full command audit (no longer partial):
- Write-path: `contract`, `delegate`, `close`, `verify`, `task` (create/set-owner/set-status), `discuss`, `recover`, `inbox_enqueue`, `inbox_recover`, `subtask_cancel`
- Read-path: `status`, `recall`, `contract_today`, `hygiene`, `doctor`, `monitor`

- **RED** `tests/unit/test_cli_dual_write.py`: one test per write command asserting both backends updated.
- **GREEN:** Each command refactored to call the centralized `write_*_op` functions from iteration 4.
- **REFACTOR:** `hygiene` command extended to validate parity (SQLite vs YAML).

### Iteration 7 — Concurrency Stress Test + Rollback Rehearsal

**Goal:** Empirically validate the thesis. Test the rollback path.

- **RED** `tests/integration/test_stress.py`:
  - 50 processes for 30 minutes: random `delegate`, `dispatch`, `close`, `recover`
  - Metrics: 0 corrupt rows, 0 deadlocks, all commits visible, parity stays at 0
  - Chaos: SIGKILL random worker mid-write, verify WAL recovery restores last committed state
  - Large dataset: 10k tasks, `get_pending` latency p99 < 100ms
  - Cross-platform: macOS + Linux (SQLite WAL fsync behavior differs)
- **RED** `tests/integration/test_rollback.py`:
  - Dual-write running; set `STATE_BACKEND=yaml_only`; continue operations
  - State remains consistent in YAML; SQLite frozen
  - Flip back to `STATE_BACKEND=dual`; parity checker re-converges
- **GREEN:** Tune indexes, add `PRAGMA synchronous=NORMAL` if needed, document rollback procedure.
- **REFACTOR:** Add `shux backup state` / `shux restore state` using SQLite online backup API.

### Iteration 8 — Read-Path Cutover

**Goal:** SQLite becomes the read source of truth. YAML continues as dual-write
for rollback safety.

- **RED** `tests/unit/test_read_cutover.py`:
  - Write via SQLite; read via `shux status` returns SQLite state
  - Mutate YAML directly; `shux status` ignores YAML divergence (SQLite wins)
  - Parity check still runs in background
- **GREEN:** Switch read functions (`get_inbox`, `get_contract`, `get_handoffs`) from YAML parse to SQL query. YAML writes continue in background.
- **REFACTOR:** Extract `StateBackend.read_*` and `StateBackend.write_*` interfaces so the swap is one import change.

### Iteration 9 — Dashboard Optimization

**Goal:** Dashboard streams from SQLite. YAML I/O contention gone.

- **RED** `tests/unit/test_dashboard_sqlite.py`:
  - `/api/status` latency p99 < 10ms (down from ~200ms on YAML)
  - Zero YAML file reads during a status poll
- **GREEN:** `dashboard-ui.py` SELECTs directly; reuse DAO layer.
- **REFACTOR:** Add `SSE /api/events` for push updates via `sqlite3` hooks (optional).

### Iteration 10 — YAML Archival + External Compat

**Goal:** Decommission YAML writes. Document external-script breakage.

- **RED** `tests/integration/test_archival.py`:
  - After archival flag set, YAML files renamed to `.yaml.bak-<ts>`
  - SQLite is sole active backend
  - `yaml_sync_queue` drained, then dropped (schema migration v2)
- **GREEN:**
  - `shux archive-yaml` command (one-shot, emits release-notes snippet)
  - `shux export yaml` compat command (for external scripts still reading YAML)
- **REFACTOR:** Remove all YAML write paths (code deletion).

**Release notes must include:** YAML files are now read-only archives. External
scripts must either use `shux export yaml` or migrate to the Python DAO API.

### Iteration 11 — phi4-mini Disposition

**Goal:** Decide fate of the harness layer now that SQL replaces its core job.

**Deletion list (hard delete in iter 11):**
- `src/superharness/harness/watcher_advisor.py` → replaced by SQL liveness queries
- `src/superharness/harness/fallback.py` (rule-based) → replaced by deterministic SQL rules
- `src/superharness/commands/inbox_watch.py::_run_health_check` → replaced by direct SQL checks

**Repurpose (keep, rewire):**
- `src/superharness/harness/review_store.py` → absorbed into `state.sqlite3.review_store` table in iter 1. Module kept as thin facade.
- `src/superharness/harness/orchestrator_advisor.py` → repurposed:
  - Routing decisions become SQL (`SELECT agent FROM review_store GROUP BY agent ORDER BY fail_rate, avg_duration LIMIT 1`)
  - `advise_failover` stays as deterministic logic (retry >= 2 → exclude failing agent)
  - phi4-mini call path deleted; advisor becomes SQL-driven
- `src/superharness/harness/owner_registry.py` → kept (availability check via CLI reachability is still useful)

**Concrete delete date:** iteration 11 is the delete iteration. No "deprecated
for a release cycle." Once iter 10 ships, iter 11 removes the code.

**Config cleanup:** `harness.yaml`'s `harness_model` block becomes noop. Either
remove from config or mark ignored with deprecation warning.

---

## Rollback Plan

Rollback is safe at any iteration through 9 because YAML remains dual-written
and authoritative until iteration 10.

**Procedure (tested in iter 7):**
1. Set env `STATE_BACKEND=yaml_only` in watcher/dispatcher.
2. Stop SQLite writes. YAML becomes sole source.
3. Run `shux doctor` to confirm YAML state is consistent.
4. Investigate SQLite issue offline.
5. Flip back to `STATE_BACKEND=dual` when fixed. Parity checker re-converges.

After iteration 10 (YAML archival), rollback requires restoring from last
`.yaml.bak-<ts>` snapshot. Document this in release notes.

---

## Durability & Operations

**Backups (added in iter 7):**
- `shux backup state [--out path]` — SQLite online backup, safe during live writes.
- `shux restore state --from path` — replaces current DB.
- Recommended cron: nightly backup to `~/.superharness-backups/`.

**Corruption recovery:**
- WAL mode: crash-safe at the OS level. Kernel panic mid-write → last committed transaction intact.
- If DB corruption detected: restore from latest backup + replay `yaml_sync_queue` history (if still in dual-write).

**Observability:**
- Every iteration adds at least one metric to `ledger` or dedicated `metrics` table (deferred to future iteration if needed).
- `shux doctor` exposes: parity-drift count, yaml_sync_queue lag, watcher singleton health, stale-inbox count, DB file size, WAL checkpoint status.

**SQLite version check:**
- At connection time: `sqlite3.sqlite_version_info >= (3, 35, 0)`. If not, emit error with install instructions. Do not silently fall back.

---

## Test Data Strategy

**Fixtures:**
- `tests/fixtures/state-small/` — 10-task project, all lifecycle states represented
- `tests/fixtures/state-large/` — 10k tasks, stress perf
- `tests/fixtures/state-corrupt/` — intentionally broken YAML for migration recovery tests

**Real-world validation:**
- Before iter 7 (cutover), run dual-write on the superharness repo itself for at least 7 days. Parity must stay at 0. If not, block promotion.

---

## External Compatibility

**Breaking changes (documented in release notes):**
- Iter 10: YAML files become read-only archives.
- External scripts parsing `inbox.yaml` / `contract.yaml` must migrate to either:
  - `shux export yaml` (snapshot compat)
  - Python DAO API (`from superharness.engine.inbox_dao import get_all`)

**Deprecation window:** iter 8 (read cutover) logs a warning whenever an
external process reads YAML (detected via `lsof` + log emission on file open).
Gives 2 release cycles before iter 10 breaks them.

---

## Summary of iteration count

| Iter | Name | Gate |
|---|---|---|
| 1 | DB Init + WAL + Versioning | - |
| 2 | Migration Bridge | iter 1 |
| 3 | DAOs + Atomic Claim + Singleton | iter 2 |
| 4 | Dual-Write Wiring (watcher + dispatcher) | iter 3 |
| 5 | Parity Monitoring | iter 4 — **hard gate: 24h zero drift** |
| 6 | CLI Command Porting (full audit) | iter 5 |
| 7 | Stress Test + Rollback Rehearsal | iter 6 |
| 8 | Read-Path Cutover | iter 7 — **requires 7-day real-world soak** |
| 9 | Dashboard Optimization | iter 8 |
| 10 | YAML Archival + External Compat | iter 9 |
| 11 | phi4-mini Deletion + Harness Repurpose | iter 10 |

---

## Key design decisions summary (for future reference)

- **Why WAL over rollback journal:** concurrent readers never block writers; required for dashboard + watcher + CLI hitting the DB simultaneously.
- **Why single `state.sqlite3` file:** one backup target, one schema version, no cross-DB foreign keys needed.
- **Why SQLite over PostgreSQL:** zero-ops, embedded, fits the superharness "single-project state" model. No daemon to run, no network to secure.
- **Why dual-write with yaml_sync_queue instead of direct YAML write in transaction:** YAML writes can fail (disk full, permissions) and are not transactional. Queue-based sync keeps SQLite commit atomic and YAML eventually consistent.
- **Why split journal into failures/decisions/ledger:** different access patterns, different retention needs, different indexes. A single table would force index bloat or scan.
- **Why optimistic concurrency on tasks:** pessimistic locking requires session state that SQLite does not model well; `version` column is standard and simple.
