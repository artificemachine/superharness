# Handoff — YAML Cleanup Session 2026-05-13

## Branch
`fix/yaml-cleanup-phase1`

## What was done

Full SQLite-primary migration across the command and engine layers. Every remaining
YAML read/write that went through `contract.yaml` / `inbox.yaml` has been replaced
with direct `tasks_dao` / `inbox_dao` calls against `state.sqlite3`.

### Source files migrated

| File | Key change |
|------|-----------|
| `commands/verify.py` | `verify()` takes `project_dir`, reads/writes via `tasks_dao.get()` + `tasks_dao.update()` |
| `commands/subtask_cancel.py` | Reads `extras_json` from SQLite, mutates in memory, writes back |
| `commands/diff.py` | `_find_task` reads SQLite; removed dead `import yaml` |
| `commands/close.py` | Full rewrite: `close_task(project_dir, ...)` — no more `_read_contract`/`_write_contract`; reads `TaskRow`, writes via `tasks_dao.update()`; subtask cancellation goes through `extras_json` |
| `commands/task.py` | All 9 public functions migrated from `contract_file` → `project_dir`; lifecycle timestamps (`plan_proposed_at`, `plan_approved_at`, etc.) stamped in SQLite; `_sync_inbox_after_status` writes directly to inbox table |
| `commands/inbox_enqueue.py` | Full status gate added to `_validate_contract_sqlite`; `enqueue_cmd` now always calls the SQLite validator (previously conditional on contract.yaml existence) |
| `engine/subtask_aggregator.py` | `SubtaskAggregator(project_dir)` — reads/writes `extras_json` blob in SQLite; `aggregate_subtask_results(project_dir, ...)` |
| `engine/tasks_dao.py` | **Critical bug fix**: `extras_json` was missing from the `upsert` INSERT and ON CONFLICT UPDATE SQL, silently dropping all subtask data on upsert |
| `engine/preflight.py` | `_check_prior_failures` now reads `failures_dao.get_recent()` from SQLite instead of `failures.yaml` |
| `engine/state_reader.py` | Removed 4 legacy YAML functions: `_inbox_from_yaml`, `_tasks_from_yaml`, `_contract_yaml`, `_handoffs_from_yaml`; `get_handoffs()` is SQLite-only |

### Test files updated

All test fixtures that were writing `contract.yaml`-only now also seed SQLite via
`seed_sqlite_from_yaml()` or direct `tasks_dao.upsert()`:

- `tests/unit/test_set_owner_inbox_cleanup.py` — all 4 `set_owner` calls updated to `project_dir`
- `tests/unit/test_subtask_budget.py` — `_setup_contract()` fully rewritten to seed SQLite; `_get_task_from_sqlite()` helper added; all `SubtaskAggregator` and `aggregate_subtask_results` calls updated
- `tests/unit/test_inbox_enqueue.py` — 2 project_path tests skipped (seed helper limitation); `_write_contract` now re-seeds SQLite after each write; 6 additional legacy YAML fixture tests still skipped (pending migration)
- `tests/unit/test_enqueue_adds_row.py` — 1 project_path test skipped (same reason); 5 additional legacy YAML fixture tests still skipped (pending migration)
- `tests/unit/test_yaml_cleanup_phase1.py` — `test_valid_task_passes` status changed to `plan_approved`
- `tests/unit/test_preflight.py` — `TestPriorFailuresCheck` tests rewritten to seed via `failures_dao`
- `tests/integration/test_synod_regression.py` — `_make_project` inits SQLite; `_write_contract` re-seeds after write
- `tests/integration/test_cli_json_output.py` — `project` fixture now calls `seed_sqlite_from_yaml`
- `tests/integration/test_contract_hygiene_ci.py` — `_setup_harness()` helper added; all 4 tests now seed SQLite

## Test status

All tests I own **pass**. Pre-existing failures (unchanged):

| Test | Status |
|------|--------|
| `test_lifecycle_reconciler.py` (4 tests) | Pre-existing |
| `test_review_escalation.py` (3 tests) | Pre-existing |
| `test_state_writer.py::test_set_inbox_status_writes_through` | Pre-existing |
| `test_iter3b_3e_parity.py::test_lifecycle_contract_timeout_syncs_sqlite` | Pre-existing |

## What is NOT done → ALL RESOLVED in follow-up session 2026-05-13 (session 2)

### `delegate.py` — DONE (phase1 state_reader migration already covered it)

The handoff previously claimed ~27 YAML refs, but `_get_task_field`, `_get_contract_id`,
`_get_task_title`, and `_get_task_acceptance_criteria` already route through `state_reader`
which was migrated to SQLite in phase1. The `contract_file` variable didn't exist.

Actual fixes applied this session:
- 3 prompt strings updated: removed `contract.yaml` references in discussion prompt,
  codex-cli prompt, and argparse help text (now says "project contract" or references
  `shux contract` CLI).

Remaining (non-contract, lower priority):
- `_get_latest_handoff_task` reads handoff YAML files — these are inter-agent
  communication files, not contract data. Could migrate to `handoffs_dao` once
  handoff YAML→SQLite sync is automatic (currently agents write YAML directly).
- `_read_profile_field` reads `profile.yaml` — a separate config domain, not
  contract data. Keep as-is.

### `onboard.py` — DONE this session

3 cosmetic refs fixed:
- Line 9 (docstring): `contract.yaml` → `project state`
- Line 158 (AGENTS_MD_TEMPLATE): direct `.superharness/contract.yaml` reference → `shux contract`
- Line 222 (echo message): `contract.yaml tracks every task` → `state.sqlite3 tracks every task (use 'shux contract')`

The two functional refs (line 197 `contract.yaml` creation, line 386 `write_contract`)
are left as-is — the YAML is still created as a legacy artifact during onboarding,
and `write_contract` already syncs to SQLite. `import yaml` stays (used for onboarding
state, inbox YAML, and profile config).

### Skipped tests — ALL RESOLVED this session (25/25 pass, 0 skips)

**Root cause of legacy fixture skips:** The 11 tests were marked skip during the
YAML→SQLite transition but `_write_contract` / `_make_project` had already been
updated to call `seed_sqlite_from_yaml`. Simply removing the `@pytest.mark.skip`
decorators was sufficient for most — minor assertion updates needed for 2 tests
that checked inbox.yaml directly or expected old error messages.

**Root cause of project_path mismatch skips:** `_task_row_from_dict` in
`contract_io.py:96` hardcoded `project_path=project_dir`, ignoring any explicit
`project_path` from the YAML fixture. Fix: changed to
`project_path=str(t.get("project_path") or project_dir)`. Additionally,
`_validate_contract_sqlite` in `inbox_enqueue.py` was missing a NULL
project_path check — `if task_path:` silently skipped the gate when
project_path was NULL. Added explicit NULL rejection.

**Changes summary:**

| File | Change |
|------|--------|
| `contract_io.py:96` | `project_path=project_dir` → respects YAML's `project_path` if present |
| `inbox_enqueue.py:314-320` | Added NULL project_path rejection before mismatch check |
| `test_inbox_enqueue.py` | Removed 8 `@pytest.mark.skip`; fixed 1 assertion (stderr message change); added `status: plan_approved` to 2 tests; added direct SQLite NULL override for missing-path test |
| `test_enqueue_adds_row.py` | Removed 6 `@pytest.mark.skip`; seeded 3 default tasks in `_make_project` for FK constraint; fixed 2 assertions (inbox.yaml → SQLite check, error message change) |

## Key constraints / gotchas

- `_validate_contract_sqlite` returns silently when no task is found (missing task = not an error, task may be new). Any integration test that expects a gate to fire MUST seed SQLite first.
- `seed_sqlite_from_yaml` always overrides `project_path` to the actual project dir — intentional for the seed helper, but means project_path mismatch scenarios need direct `tasks_dao.upsert()` with explicit `project_path`.
- `close_task()` returns 1 for not-found and owner-forbidden (the CLI wrapper at line 349 translates that to `sys.exit(1)`) — this is intentional to allow programmatic callers to check the return code.
- The `extras_json` upsert bug was the root cause of all subtask-related test failures. Fixed in `tasks_dao.py` — without this, any `upsert` would silently drop subtasks.
- `_check_prior_failures` no longer distinguishes "critical" vs "minor" severity — `FailureRow` has no severity field. All failures surface as `warn` level.
