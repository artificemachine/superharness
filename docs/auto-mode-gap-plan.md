# Auto-Mode Gap Implementation Plan (TDD Iterations)

> Companion to `docs/auto-mode-gap.md`. Each iteration follows Red → Green → Refactor. Iterations are sized for one PR each, ordered by dependency and risk.
> Date: 2026-04-27

## Sequencing rationale

The 8 gaps from the analysis doc are not equal in risk or coupling. This plan reorders them by **what unblocks what** and **what carries the least migration risk first**:

```
iter 1 ─ failure classifier (gap 3)        standalone, no migration
   │
iter 2 ─ unified lifecycle reconciler (gap 2)   replaces 4 existing reconcilers
   │
   ├── iter 3 ─ SQLite as source of truth (gap 1)    biggest, riskiest, but iter 1+2
   │            (sub-iterations 3a..3e)               work whether SoT is YAML or SQLite
   │
   ├── iter 4 ─ in_progress task timeout (gap 7)     adds row to lifecycle table
   │
   ├── iter 5 ─ plan quality gate (gap 4)            standalone module
   │
   ├── iter 6 ─ report verification gate (gap 5)     standalone module
   │
   ├── iter 7 ─ peer review escalation (gap 6)       lifecycle table change
   │
   └── iter 8 ─ dashboard error surface (gap 8)      consumes iter 1 output
```

The classifier comes first because it is pure-functional, has zero migration cost, and immediately improves every dashboard message. The lifecycle reconciler comes second because it consolidates four existing reconcilers into one rule table, which makes adding gaps 4, 7 trivial.

The SQLite migration sits in the middle on purpose: by then, gaps 1, 2, 3 reconcilers and classifier work regardless of backend, so the migration can be done store by store without holding everything else hostage.

## Iteration 0: Test infrastructure

> Prerequisite for everything below. One PR.

### Red

- `tests/test_state_consistency.py` (new): assertions that fail today, like `test_yaml_sqlite_parity_after_set_status`.
- `tests/conftest.py`: add `clean_harness` fixture that creates a tmp `.superharness/` with valid empty contract/inbox/profile.
- Add a `frozen_time` fixture using `freezegun` for deterministic timeout testing.

### Green

- Implement the fixtures, run the parity test (it should fail), confirm failure mode is the expected one (drift between stores).

### Refactor

- Pull common harness setup from existing tests into the new fixtures.

### Acceptance

- `pytest tests/test_state_consistency.py -q` runs.
- The fixture is reused by at least three existing tests.

---

## Iteration 1: failure classifier (gap 3)

> New module. No migration. Pure function. ~2 days.

### Red

`tests/engine/test_failure_classifier.py`:

```python
def test_classifies_bash_unbound_variable_as_permanent_block()
def test_classifies_timeout_as_transient()
def test_classifies_quota_exceeded_as_surface_to_operator()
def test_classifies_no_output_as_no_op()
def test_classifies_agent_crash_as_retry_once()
def test_classifies_missing_contract_task_as_permanent_block()
def test_unknown_failure_falls_back_to_unknown_class()
def test_classifier_returns_explanation_string_for_dashboard()
```

Each test feeds a synthetic `(launcher_rc, error_text, task_log_tail)` and asserts the returned `FailureClassification(category, retryable, explain)`.

### Green

`src/superharness/engine/failure_classifier.py`:

```python
@dataclass
class FailureClassification:
    category: Literal["permanent_block", "transient", "quota", "agent_crash", "no_op", "unknown"]
    retryable: bool
    explain: str  # human-readable, surfaces in dashboard

def classify(launcher_rc: int, error_text: str, log_tail: str) -> FailureClassification:
    # regex+heuristics, no LLM
    ...
```

Implementation is pure: regex pass over `log_tail`, then `error_text`, then fallback by `launcher_rc`. No I/O.

### Refactor

`src/superharness/commands/inbox_dispatch.py`:

- In `_mark_item_failed`, after building `fail_reason`, also call `classify(...)` and write `failure_class` and `failure_explain` fields on the inbox item.
- `auto_retry_failed` reads `failure_class` to decide: skip if `permanent_block` or `quota`; retry only if `retryable=True`.

### Acceptance

- New tests pass.
- Existing tests pass unchanged.
- Re-running the orphaned-subtask scenario from this session: the dispatcher now records `failure_class: permanent_block` instead of letting `auto_retry` cycle them.

---

## Iteration 2: unified lifecycle reconciler (gap 2)

> Consolidation. Replaces 4 reconcilers with 1 rule table. ~3 days.

### Red

`tests/engine/test_lifecycle_reconciler.py`:

```python
def test_paused_item_no_reason_after_30m_becomes_failed()
def test_paused_item_with_reason_is_immune_to_timeout()
def test_review_requested_after_120m_reverts_to_report_ready()
def test_discussion_terminal_archives_in_progress_task()
def test_in_progress_task_after_180m_is_archived()  # NEW behavior, gap 7 preview
def test_lifecycle_rules_are_data_driven()  # adding a row affects no other code
```

Tests use `frozen_time` fixture. Each test sets up a state, advances time, runs `reconcile_lifecycle`, asserts transition.

### Green

`src/superharness/engine/lifecycle_rules.py`:

```python
@dataclass(frozen=True)
class LifecycleRule:
    state: str
    timeout_minutes: int
    on_timeout: Literal["fail", "archive", "revert", "escalate"]
    revert_to: str | None = None
    skip_if_field: str | None = None  # e.g. "reason" for manually paused

LIFECYCLE_RULES = [
    LifecycleRule("paused",           30,  "fail",    skip_if_field="reason"),
    LifecycleRule("review_requested", 120, "revert",  revert_to="report_ready"),
    LifecycleRule("in_progress",      180, "archive"),  # gap 7
]
```

`src/superharness/commands/inbox_watch.py`:

- New `_reconcile_lifecycle(project_dir)` reads rules, scans contract+inbox, applies transitions.
- Discussion sync is its own pass (different shape: scans `discussions/*/state.yaml`).

### Refactor

- Delete `_reconcile_paused_dead_pids`, `_reconcile_paused_timeout`, `_reconcile_stale_review_requested`.
- Wire `_reconcile_lifecycle` into the watcher tick.
- Keep `_reconcile_zombies` (different concern: dead PIDs) and `_reconcile_discussion_contract` (different shape: cross-store).

### Acceptance

- New tests pass.
- The four existing tests for paused/review/discussion reconcilers still pass after migration.
- Net code: about -150 lines, +80 lines (consolidation).

---

## Iteration 3: SQLite as source of truth (gap 1)

> The big one. Five sub-iterations. ~2 weeks total.

### 3a: state_writer skeleton

#### Red

`tests/engine/test_state_writer.py`:

```python
def test_set_task_status_writes_sqlite_first()
def test_set_task_status_emits_yaml_export_event()
def test_set_inbox_status_writes_sqlite_first()
def test_writes_are_atomic_under_concurrent_callers()
```

#### Green

`src/superharness/engine/state_writer.py` (new):

```python
def set_task_status(project_dir, task_id, to_status, from_status=None) -> bool
def set_inbox_status(project_dir, item_id, to_status, from_status=None, **fields) -> bool
def upsert_handoff(project_dir, handoff_id, content) -> bool
```

All write SQLite under transaction. Emit a `yaml_export_pending` event (no-op until 3e).

#### Refactor

- Identify all current callers of `_set_inbox_status`, `set_task_status` shell-outs, direct YAML edits. Tag them for migration in 3b/3c.

### 3b: contract writes through state_writer

#### Red

- `test_contract_set_status_does_not_drift` (the parity test from iter 0).

#### Green

- Migrate every caller of `_set_task_status` (dashboard-ui, close, verify, plan_propose, plan_approve) to `state_writer.set_task_status`.

#### Refactor

- Delete the duplicate write paths in dashboard-ui.py.

### 3c: inbox writes through state_writer

Same pattern as 3b for inbox items: dispatcher, watcher, dashboard, set_status callers.

### 3d: discussion writes through state_writer

Same pattern for `discussions/state.yaml` via `state_writer.upsert_discussion_state`.

### 3e: switch default backend to sqlite_only

#### Red

- `test_state_reader_ignores_yaml_edits_in_sqlite_only_mode`
- `test_export_command_regenerates_yaml_from_sqlite`

#### Green

- `state_reader._get_backend` defaults to `sqlite_only`.
- New `shux export` command regenerates `.superharness/*.yaml` from SQLite (one-shot, idempotent).
- Pre-commit hook runs `shux export` so YAML diffs stay reviewable.

#### Refactor

- Delete `yaml_sync_queue` table and its drainer.
- Document migration in `docs/state-backend.md`.

### Acceptance

- Direct SQLite updates persist through watcher cycles (the bug from this session).
- Direct YAML edits do not affect runtime behavior. Operators get a clear "edits to YAML are ignored, use shux commands" error path.
- 100% of the orphaned-subtask scenario is prevented at the writer layer.

---

## Iteration 4: in_progress task timeout (gap 7)

> Trivial after iteration 2. ~1 day.

### Red

`test_in_progress_task_after_180m_is_archived`. Already written in iter 2 as a placeholder, now wired up.

### Green

- Add `LifecycleRule("in_progress", 180, "archive")` to `LIFECYCLE_RULES`.

### Refactor

- Document the timeout in `docs/auto-mode-gap.md` lifecycle table.

### Acceptance

- A task stuck in `in_progress` for 3 hours is archived with a `failed_reason: "in_progress timeout (180m)"`.
- Operator can configure via `profile.yaml: in_progress_timeout_minutes`.

---

## Iteration 5: plan quality gate (gap 4)

> Standalone module. Wires into `auto_approve_plans`. ~3 days.

### Red

`tests/engine/test_plan_validator.py`:

```python
def test_plan_missing_tdd_block_is_rejected()
def test_plan_missing_tdd_red_section_is_rejected()
def test_plan_with_complete_tdd_passes()
def test_plan_addresses_all_acceptance_criteria()
def test_plan_with_unaddressed_criterion_is_rejected()
def test_plan_touching_too_many_files_is_rejected_unless_justified()
def test_plan_with_todo_markers_is_rejected()
def test_plan_with_no_risks_section_is_rejected()
def test_validation_failure_includes_actionable_reason()
```

### Green

`src/superharness/engine/plan_validator.py`:

```python
@dataclass
class PlanValidation:
    passed: bool
    failures: list[str]  # human-readable, surfaces in dashboard

def validate_plan(plan_handoff: dict, contract_task: dict) -> PlanValidation
```

### Refactor

- `_auto_approve_plans` (in `inbox_watch.py`) calls `validate_plan` first. If it fails, leaves the plan in `plan_proposed` with a `validation_failures` field. Operator sees only flagged plans.
- Dashboard plan-preview panel shows the failures inline with each rejected plan.

### Acceptance

- Plans with complete TDD blocks auto-approve.
- Plans without TDD blocks show up in operator queue with reason "missing tdd.refactor section".
- Operator load drops from "every plan" to "plans needing judgment".

---

## Iteration 6: report verification gate (gap 5)

> Standalone module. Wires into `auto_close_report_ready`. ~3 days.

### Red

`tests/engine/test_report_verifier.py`:

```python
def test_report_with_tests_passed_passes()
def test_report_missing_tests_passed_warns_but_does_not_block_when_explicit()
def test_report_with_short_outcome_is_rejected()
def test_report_missing_context_field_is_rejected()
def test_report_referencing_nonexistent_pr_url_is_rejected()
def test_project_tests_failing_blocks_close()
def test_project_tests_passing_unblocks_close()
```

### Green

`src/superharness/engine/report_verifier.py`:

```python
@dataclass
class ReportVerification:
    passed: bool
    failures: list[str]
    suggested_action: Literal["close", "operator_review", "fail"]

def verify_report(report_handoff: dict, contract_task: dict, project_dir: str) -> ReportVerification
```

Optionally invokes `pytest tests/ -q` if a `tests/` directory exists.

### Refactor

- `_auto_close_report_ready` calls `verify_report` first. Closes only if `suggested_action == "close"`.
- Dashboard task-report panel shows verification failures inline.

### Acceptance

- Reports with complete handoffs and passing tests auto-close.
- Reports with short outcomes or failing tests stay in operator queue with reason highlighted.
- The mock.alpha case from this session would have flagged "outcome too short" instead of silently sticking.

---

## Iteration 7: peer review escalation (gap 6)

> Lifecycle table change plus reviewer chain config. ~2 days.

### Red

`tests/engine/test_review_escalation.py`:

```python
def test_review_requested_with_no_reviewer_after_timeout_escalates_to_next()
def test_review_requested_with_chain_exhausted_escalates_to_operator()
def test_review_completed_before_timeout_does_not_escalate()
```

### Green

- Modify the `review_requested` lifecycle rule from `revert` to `escalate`.
- New `review_chain` field per task: ordered list of reviewers.
- New `review_chain_index` cursor: advances on each timeout.
- When chain exhausted, mark task `review_requested` with `escalated: operator` flag.

### Refactor

- Update `peer_reviewers` config doc to describe chain semantics.

### Acceptance

- Mock.beta-style stuck reviews escalate to the next reviewer, then to the operator with a clear flag.
- Operator sees only escalated reviews, not every `review_requested` task.

---

## Iteration 8: dashboard error surface (gap 8)

> Pure UI, consumes iter 1 output. ~2 days.

### Red

`tests/dashboard/test_error_panel.py`:

```python
def test_panel_shows_failed_items_grouped_by_failure_class()
def test_panel_shows_last_20_lines_of_log_inline()
def test_panel_filters_out_resolved_failures()
def test_panel_count_matches_inbox_failed_count()
```

### Green

- New panel `recentFailures` in `dashboard.html`.
- API endpoint `/api/recent-failures` returns latest N failed items with `failure_class`, `failure_explain`, `log_tail`.
- Panel renders one row per failure with a copy button (already exists pattern).

### Refactor

- Move the existing scattered "failed: N" indicators into the new panel as a single source.

### Acceptance

- Operator sees all recent failures in one panel without leaving the dashboard.
- Each failure shows its class (`permanent_block`, `transient`, etc.) plus log tail.
- The `tail launcher-logs/` reflex from this session is gone.

---

## Cross-iteration concerns

### TDD discipline

- Every iteration is RED first. PR description must include the failing-test commit hash.
- No iteration merges until every test in it passes.
- Follow the project rule: every commit appends to `CHANGELOG.md`.

### Backwards compatibility

- Iterations 1, 2, 5, 6, 7, 8 are additive, no compat concerns.
- Iteration 3 (SQLite SoT) breaks anyone editing YAML directly. Provide a one-time migration command and surface a clear error when YAML drift is detected.
- Iteration 4 introduces a new auto-archival behavior. Default 180m is conservative, configurable.

### Ship cadence

- Each iteration is one PR.
- Iterations 1, 2 ship to `main` independently.
- Iteration 3 (3a..3e) lives on a long-running branch `feat/sqlite-source-of-truth` and merges as a single PR after all sub-iterations are green.
- Iterations 4..8 ship independently after their dependencies (iter 2 for 4 and 7).

### Risks

| Iteration | Risk | Mitigation |
|---|---|---|
| 3 (SQLite SoT) | Existing scripts that edit YAML directly break | Detect drift, log a warning for one release before erroring. Document the `shux export` round-trip. |
| 5 (plan gate) | Strict heuristics block valid plans | Heuristics are individually toggleable in profile.yaml. |
| 6 (report gate) | `pytest tests/ -q` is slow or flaky | Cache last-pass timestamp, only re-run if files changed since. |
| 7 (escalation) | Reviewers chained incorrectly create loops | Validate chain on config load, prevent self-reference. |

## Summary

8 iterations, ordered by dependency and risk. The first two are foundation, the third is the big migration, the rest are small and standalone. Following TDD and the project's commit hygiene means each iteration is a single reviewable PR.

After iteration 8, the operator session described in the gap analysis ("two items, both with a clear reason") is reality. Every gap from that doc has a corresponding iteration above. No iteration depends on more than one earlier iteration.

## References

- Gap analysis: `docs/auto-mode-gap.md`
- Existing reconcilers (replaced in iteration 2): `src/superharness/commands/inbox_watch.py`
- Failure record points (consumed by iteration 1): `src/superharness/commands/inbox_dispatch.py`
- Profile flags: `.superharness/profile.yaml`
- Lifecycle spec: `superharness/protocol/spec.md`
