# State Backend Interfaces — Authoritative Contract

> **This document is the single source of truth for every agent implementing
> any iteration of the SQLite ledger migration.** Function names, signatures,
> module paths, exception classes, and semantics defined here are mandatory.
> Do not rename, add, or drop parameters without updating this doc first.
>
> Companion plan: `docs/plans/sqlite-ledger-migration.md`

## 0. Scope & Ground Rules

### Who reads this
Any agent (Claude, Gemini, or human) writing code for iterations 1-11 of the
SQLite migration. Read this file in full before writing code.

### Drift policy
If an implementation needs a signature not defined here, first open a PR that
updates this doc. Never silently deviate.

### Naming conventions
- Functions: `snake_case`, verb-first (`get_*`, `claim_*`, `append_*`, `update_*`).
- DAO modules: `<entity>_dao.py` (e.g. `inbox_dao.py`, `tasks_dao.py`).
- Dataclasses for structured returns: `<Entity>Row` for one, `<Entity>View` for aggregates.
- Private helpers: leading underscore.
- Tests: `tests/unit/db/test_<module>.py`.

### Import-side-effect rule
Importing any module here MUST NOT open a DB connection, MUST NOT create
tables, MUST NOT read config. All I/O happens inside called functions only.

---

## 1. Module Layout

```
src/superharness/engine/
  db.py                    # connection + migrations
  inbox_dao.py             # inbox table CRUD + claim
  tasks_dao.py             # tasks + dependencies CRUD
  handoffs_dao.py          # handoff history (row-per-event)
  failures_dao.py          # failures log
  decisions_dao.py         # decisions log
  ledger_dao.py            # operational trace (dispatched, heartbeat, ...)
  review_dao.py            # owner outcome stats (absorbs harness/review_store.py)
  watcher_singleton.py     # watcher instance lease
  yaml_sync.py             # dual-write queue worker
  parity.py                # drift detection
  migrate_yaml.py          # one-shot YAML → SQLite import
  state_errors.py          # exception hierarchy
```

All new modules live in `src/superharness/engine/`. No exceptions.

---

## 2. Exception Hierarchy

Defined in `state_errors.py`. Every DAO raises only these.

```python
class StateError(Exception):
    """Base for all state-backend errors."""

class ConnectionError(StateError):
    """Raised when the DB cannot be opened or PRAGMA setup fails."""

class SchemaError(StateError):
    """Raised on version mismatch, missing tables, or migration failure."""

class ConcurrencyError(StateError):
    """Raised on optimistic-concurrency version conflicts."""

class NotFoundError(StateError):
    """Raised when a required row is absent (use sparingly; prefer None returns)."""

class ParityError(StateError):
    """Raised when dual-write parity check finds unreconcilable drift."""

class SingletonConflict(StateError):
    """Raised when two watchers try to hold the singleton lease simultaneously."""
```

**Rule:** DAO code must not raise `sqlite3.Error` to callers. Wrap and re-raise as `StateError` subclass.

---

## 3. `db.py` — Connection & Migrations

### `get_connection(project_dir: str) -> sqlite3.Connection`

Opens `<project_dir>/.superharness/state.sqlite3`.

Must set:
- `PRAGMA journal_mode=WAL`
- `PRAGMA foreign_keys=ON`
- `PRAGMA busy_timeout=5000` (milliseconds)

Raises `ConnectionError` if SQLite version < 3.35 or file cannot be opened.

Thread-safety: each caller gets its own connection. No global connection pool
in iteration 1 (may be added in a later iteration behind this function).

### `init_db(conn: sqlite3.Connection) -> None`

Idempotent. Runs migrations up to the current schema version defined in
`schema_migrations` list. Safe to call on every startup.

### `CURRENT_SCHEMA_VERSION: int`

Module-level constant. Bumped whenever a new migration is added.

### `_MIGRATIONS: list[Callable[[sqlite3.Connection], None]]`

Ordered list, index = version - 1. Each migration wraps its own transaction.

---

## 4. `inbox_dao.py` — Inbox Operations

### Dataclasses

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class InboxRow:
    id: str
    task_id: str
    target_agent: str
    status: str
    priority: int
    retry_count: int
    max_retries: int
    pid: int | None
    project_path: str | None
    plan_only: bool
    failed_reason: str | None
    created_at: str              # ISO8601 UTC
    launched_at: str | None
    last_heartbeat: str | None
    paused_at: str | None
    failed_at: str | None
    done_at: str | None
```

### Functions

```python
def enqueue(
    conn: sqlite3.Connection,
    *,
    id: str,
    task_id: str,
    target_agent: str,
    priority: int = 2,
    max_retries: int = 3,
    project_path: str | None = None,
    plan_only: bool = False,
) -> InboxRow: ...
```
Inserts a new inbox row with `status='pending'`, `created_at=now()`.
Raises `IntegrityError` (sqlite3 wrapped as `StateError`) on duplicate id.

```python
def get(conn: sqlite3.Connection, id: str) -> InboxRow | None: ...
```

```python
def get_all(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    target_agent: str | None = None,
    limit: int | None = None,
) -> list[InboxRow]: ...
```
Returns rows ordered by `priority DESC, created_at ASC`.

```python
def claim_next(
    conn: sqlite3.Connection,
    *,
    target_agent: str,
    pid: int,
    now: str,
) -> InboxRow | None: ...
```
**The atomic claim primitive.** Executes:
```sql
UPDATE inbox
SET status='launched', pid=?, launched_at=?, last_heartbeat=?
WHERE id = (
  SELECT id FROM inbox
  WHERE status='pending' AND target_agent=?
  ORDER BY priority DESC, created_at ASC
  LIMIT 1
)
RETURNING *;
```
Returns the claimed row or `None` if no pending work. Two callers running
concurrently: exactly one gets the row.

```python
def update_status(
    conn: sqlite3.Connection,
    id: str,
    *,
    from_status: str,
    to_status: str,
    now: str,
    reason: str | None = None,
) -> bool: ...
```
Transitions a row only if current status matches `from_status`. Returns True
on success, False if the row was not in the expected state (caller decides
how to handle).

```python
def mark_heartbeat(conn: sqlite3.Connection, id: str, now: str) -> None: ...
```
Sets `last_heartbeat=now` unconditionally. No-op if row absent.

```python
def get_stale(
    conn: sqlite3.Connection,
    *,
    timeout_seconds: int,
    now: str,
) -> list[InboxRow]: ...
```
Returns rows where `status IN ('launched','running')` AND `last_heartbeat <
(now - timeout_seconds)`. Does not mutate rows — caller decides action.

```python
def set_retry(
    conn: sqlite3.Connection,
    id: str,
    retry_count: int,
    failed_reason: str,
    now: str,
) -> None: ...
```

---

## 5. `tasks_dao.py` — Tasks + Dependencies

### Dataclasses

```python
@dataclass(frozen=True)
class TaskRow:
    id: str
    title: str
    owner: str | None
    status: str
    effort: str | None
    project_path: str | None
    development_method: str | None
    acceptance_criteria: list[str]
    test_types: list[str]
    out_of_scope: list[str]
    definition_of_done: list[str]
    context: str | None
    tdd: dict | None
    version: int
    created_at: str
    plan_proposed_at: str | None
    plan_approved_at: str | None
    in_progress_at: str | None
    report_ready_at: str | None
    done_at: str | None
    cancelled_at: str | None
    blocked_by: list[str]           # populated from task_dependencies
```

### Functions

```python
def upsert(conn: sqlite3.Connection, task: TaskRow) -> TaskRow: ...
```
Insert or update. Uses `INSERT ... ON CONFLICT(id) DO UPDATE`. Bumps `version`.
JSON-encodes list/dict fields. Does NOT touch `task_dependencies` — call
`set_dependencies()` separately.

```python
def get(conn: sqlite3.Connection, id: str) -> TaskRow | None: ...
```
Returns the row with `blocked_by` populated from `task_dependencies`.

```python
def get_all(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    owner: str | None = None,
) -> list[TaskRow]: ...
```

```python
def update(
    conn: sqlite3.Connection,
    id: str,
    version: int,
    changes: dict,
) -> TaskRow: ...
```
**Optimistic concurrency.** Executes `UPDATE tasks SET ... , version=version+1
WHERE id=? AND version=?`. Raises `ConcurrencyError` if row version doesn't match.

```python
def set_dependencies(
    conn: sqlite3.Connection,
    task_id: str,
    prerequisites: list[str],
) -> None: ...
```
Replaces existing rows in `task_dependencies` for this task_id.

```python
def get_unblocked(
    conn: sqlite3.Connection,
    *,
    status_filter: list[str] | None = None,
) -> list[TaskRow]: ...
```
Returns tasks whose prerequisites are all in `status='done'`.

---

## 6. `handoffs_dao.py` — History Preserving

### Dataclasses

```python
@dataclass(frozen=True)
class HandoffRow:
    id: int
    task_id: str
    phase: str               # plan | report | review
    status: str              # plan_proposed | plan_approved | report_ready | review_failed | review_approved
    from_agent: str | None
    to_agent: str | None
    content: str | None
    metadata: dict
    created_at: str
```

### Functions

```python
def append(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    phase: str,
    status: str,
    from_agent: str | None = None,
    to_agent: str | None = None,
    content: str | None = None,
    metadata: dict | None = None,
    now: str,
) -> HandoffRow: ...
```
**Append-only.** Never updates or deletes existing rows.

```python
def get_history(
    conn: sqlite3.Connection,
    task_id: str,
) -> list[HandoffRow]: ...
```
Returns all handoffs for a task, ordered `created_at ASC`.

```python
def get_latest(
    conn: sqlite3.Connection,
    task_id: str,
    phase: str,
) -> HandoffRow | None: ...
```
Returns the most recent handoff of the given phase for this task.

---

## 7. `failures_dao.py` / `decisions_dao.py` / `ledger_dao.py`

All three follow the same shape. Example for failures:

```python
@dataclass(frozen=True)
class FailureRow:
    id: int
    task_id: str | None
    agent: str | None
    pattern: str | None
    error_snippet: str | None
    created_at: str

def record(
    conn: sqlite3.Connection,
    *,
    task_id: str | None = None,
    agent: str | None = None,
    pattern: str | None = None,
    error_snippet: str | None = None,
    now: str,
) -> FailureRow: ...

def get_recent(
    conn: sqlite3.Connection,
    *,
    task_id: str | None = None,
    agent: str | None = None,
    limit: int = 100,
) -> list[FailureRow]: ...
```

`decisions_dao.record()` takes: `agent, task_id, decision, reason, alternatives`.
`ledger_dao.record()` takes: `task_id, agent, action, details (dict)`.

---

## 8. `review_dao.py` — Absorbs Harness ReviewStore

Replaces `src/superharness/harness/review_store.py`. Same table schema,
now living in `state.sqlite3`.

```python
@dataclass(frozen=True)
class OwnerStats:
    owner: str
    task_count: int
    avg_score: float
    avg_duration_s: float
    fail_rate: float

def record(
    conn: sqlite3.Connection,
    *,
    owner: str,
    task_type: str,
    duration_s: float,
    score: float,
    failed: bool,
    now: str,
) -> None: ...

def stats(conn: sqlite3.Connection, owner: str) -> OwnerStats: ...

def rank_owners(
    conn: sqlite3.Connection,
    *,
    task_type: str | None = None,
    min_task_count: int = 3,
) -> list[OwnerStats]: ...
```
`rank_owners` returns owners ordered by `(fail_rate ASC, avg_duration_s ASC)`
for data-driven routing (replaces phi4-mini routing).

---

## 9. `watcher_singleton.py`

```python
@dataclass(frozen=True)
class SingletonLease:
    pid: int
    hostname: str
    started_at: str
    last_heartbeat: str

def acquire(
    conn: sqlite3.Connection,
    *,
    pid: int,
    hostname: str,
    now: str,
    stale_after_seconds: int = 120,
) -> SingletonLease: ...
```
Acquires the singleton lease. Behavior:
1. If no existing row: INSERT succeeds.
2. If existing row's `last_heartbeat` is older than `stale_after_seconds`:
   UPDATE with new PID succeeds (stale takeover).
3. Otherwise: raises `SingletonConflict`.

```python
def heartbeat(conn: sqlite3.Connection, pid: int, now: str) -> bool: ...
```
Updates `last_heartbeat` if the caller's PID owns the lease. Returns True on
success, False if another PID took over (caller should exit).

```python
def release(conn: sqlite3.Connection, pid: int) -> None: ...
```
Deletes the lease row if owned by this PID. No-op otherwise.

---

## 10. `yaml_sync.py` — Dual-Write Queue

### Functions

```python
def enqueue_op(
    conn: sqlite3.Connection,
    *,
    op_type: str,             # upsert_task | update_inbox | append_handoff | ...
    payload: dict,
    now: str,
) -> int: ...
```
Inserts a row in `yaml_sync_queue`. Must be called inside the same transaction
as the authoritative SQLite write it shadows.

```python
def drain(
    conn: sqlite3.Connection,
    project_dir: str,
    *,
    max_ops: int = 100,
    max_attempts: int = 5,
) -> DrainReport: ...

@dataclass(frozen=True)
class DrainReport:
    applied: int
    failed: int
    pending_remaining: int
```
Reads pending ops, applies each to the YAML files, updates status.
Called from the watcher tick. Never raises — aggregates errors into the report.

### Op-type handlers

One function per op_type, living as private functions in `yaml_sync.py`:
- `_apply_upsert_task(project_dir, payload)`
- `_apply_update_inbox(project_dir, payload)`
- `_apply_append_handoff(project_dir, payload)`
- `_apply_record_failure(project_dir, payload)`
- `_apply_record_decision(project_dir, payload)`

Each handler is idempotent and atomic per-file (write to `.tmp`, `os.replace`).

---

## 11. `parity.py` — Drift Detection

### Dataclasses

```python
@dataclass(frozen=True)
class TableDrift:
    table: str
    only_in_db: int
    only_in_yaml: int
    mismatched: int

@dataclass(frozen=True)
class ParityReport:
    checked_at: str
    healthy: bool                  # True iff all drifts are zero
    drifts: list[TableDrift]
    yaml_sync_lag: int             # count of pending ops
```

### Functions

```python
def check_parity(
    conn: sqlite3.Connection,
    project_dir: str,
) -> ParityReport: ...
```
For each canonical table (tasks, inbox, handoffs), compares SQLite rows to
YAML rows. Returns full report. Does not mutate state.

```python
def heal_parity(
    conn: sqlite3.Connection,
    project_dir: str,
    report: ParityReport,
) -> int: ...
```
Attempts to heal drifts by re-enqueuing sync ops. Returns number of ops enqueued.
Does not heal `only_in_yaml` drifts (those require human review).

---

## 12. `migrate_yaml.py` — One-Shot Migration

```python
@dataclass(frozen=True)
class MigrationReport:
    tasks_imported: int
    inbox_imported: int
    handoffs_imported: int
    failures_imported: int
    decisions_imported: int
    review_imported: int
    errors: list[str]              # per-file errors, non-fatal
    worker_dirs_migrated: list[str]

def migrate_all_to_sqlite(
    conn: sqlite3.Connection,
    project_dir: str,
) -> MigrationReport: ...
```

**Idempotency:** uses `INSERT ... ON CONFLICT DO NOTHING` / `upsert()` patterns.
Running twice produces the same final state.

**Error handling:** per-file try/except. Failure in one file is logged to
`errors` and written to `ledger_dao` as `action='migration_error'`. Migration
of other files continues.

**Worker project detection:** walks `~/.superharness-workers/<name>/.superharness/`
via symlink inspection. Worker dirs that point to the same `.superharness/` via
symlink are skipped (deduplicated).

**Reviews merging:** if `<project_dir>/.superharness/reviews.db` exists (from
phi4-mini harness layer), its rows are imported into `review_store` table.

---

## 13. Transaction Semantics

### General rule
Each public DAO function runs in **its own transaction** unless the function
accepts an existing connection in an already-open transaction. Callers do not
wrap single DAO calls in their own transactions.

For multi-statement operations that must be atomic across multiple DAOs (e.g.,
"atomically claim inbox row + ledger entry"), use the shared context manager:

```python
from superharness.engine.db import transaction

with transaction(conn):
    row = inbox_dao.claim_next(conn, ...)
    ledger_dao.record(conn, ..., action="dispatched")
    yaml_sync.enqueue_op(conn, op_type="update_inbox", payload=...)
```

`transaction()` is a reentrant context manager: nested calls are no-ops; only
the outermost `__exit__` commits/rollbacks.

### Savepoints
Not used in this migration. Keep it simple.

### Isolation
Default (deferred). WAL mode already gives us snapshot isolation for readers.

---

## 14. Time Handling

All timestamps are **ISO8601 UTC strings** (format: `2026-04-24T18:00:00Z`).

All DAO functions that need `now` accept it as a parameter of type `str`. This
makes tests deterministic. A helper lives in `db.py`:

```python
def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

**Never** call `datetime.now()` inside a DAO function.

---

## 15. Test Patterns

### Fixture: `db_conn`

Defined once in `tests/unit/db/conftest.py`:

```python
@pytest.fixture
def db_conn(tmp_path) -> Iterator[sqlite3.Connection]:
    from superharness.engine.db import get_connection, init_db
    project = tmp_path
    (project / ".superharness").mkdir()
    conn = get_connection(str(project))
    init_db(conn)
    yield conn
    conn.close()
```

Every DAO test uses `db_conn`. No test opens its own connection.

### Time mocking

Tests pass fixed timestamps:

```python
def test_claim(db_conn):
    inbox_dao.enqueue(db_conn, id="i1", task_id="t1", target_agent="claude-code")
    row = inbox_dao.claim_next(db_conn, target_agent="claude-code", pid=42, now="2026-01-01T00:00:00Z")
    assert row.launched_at == "2026-01-01T00:00:00Z"
```

### Concurrency tests

Use `threading` with `time.sleep(0.01)` to stage contention. Assertions must
not depend on wall-clock timing.

---

## 16. Code Style

- Use `from __future__ import annotations` at top of every module.
- `sqlite3.Row` as `row_factory` — access columns by name.
- Named parameters in all public DAO functions (`*,` separator enforced).
- Docstrings on every public function — one-line purpose, then param/return
  notes only if non-obvious.
- No `print()` statements in DAO modules. Use `logging.getLogger(__name__)`.
- No global state except module-level constants.

---

## 17. Checklist Before Submitting Code

- [ ] All public functions match signatures in this doc exactly.
- [ ] All list/dict fields are JSON-encoded in DB, decoded in dataclasses.
- [ ] `from __future__ import annotations` at top of file.
- [ ] No `sqlite3.Error` raised to callers — wrapped as `StateError`.
- [ ] All time parameters are ISO8601 UTC strings, not `datetime` objects.
- [ ] Tests use `db_conn` fixture, not custom connections.
- [ ] Docstring on every public function.
- [ ] No imports with side effects (no connection opened at import time).
- [ ] `mypy` / `pyright` passes with strict mode (no `Any` returns).
