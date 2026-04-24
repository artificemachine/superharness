# Defense Layers — Full TDD Iteration Plan

**Date:** 2026-04-24
**Commit base:** `ab29e93` + in-session working-tree fixes (not yet committed)
**Purpose:** Ordered, TDD-structured plan to harden the superharness protocol against schema drift, silent failures, and broken contract invariants. Derived from findings in `claude_superharness_review.md`, `codex_superharness_review.md`, and `gemini_superharness_review.md`.

---

## Status of Layers

| Layer | Description | Status |
|---|---|---|
| 1 | Pre-commit YAML parse gate (hook 1b.2) | **Done (this session)** |
| 2 | `shux contract --validate` CLI subcommand | Planned — Iteration 1 |
| 3b | Warn-only Pydantic validation on write | Planned — Iteration 2 |
| 3a | Strict Pydantic enforcement on write | Planned — Iteration 5 (after data reconciliation) |
| #7 | Paused-pid reconciliation in watcher | Planned — Iteration 6 |
| PID | daemon.pid.json / operator-state.json split | Planned — Iteration 7 |

---

## Iteration 0 — Foundation (Done)

All items below are already applied in the working tree. They must be committed in a single PR before any further iteration branches.

### What was done

| Fix | File | Finding |
|---|---|---|
| Pre-commit hook 1b.2: reject invalid contract YAML on stage | `~/dotfiles/githooks/pre-commit` | Codex/Gemini #1 |
| `inbox_watch` → fix module target in daemon subprocess | `src/superharness/commands/daemon.py:101` | Codex/Gemini #2 |
| Add 4 missing `TaskStatus` enum values | `src/superharness/engine/schemas.py` | Codex/Gemini #5 |
| Narrow `except Exception` in dependency check | `src/superharness/engine/inbox.py:179` | Codex/Gemini #6 |
| `.superharness/.gitignore` entries | `.superharness/.gitignore` | Codex #7 |
| `_safe_task_id_for_path` + dispatcher fix | `src/superharness/commands/inbox_dispatch.py` | Claude review #5 |
| Regression test for path sanitization | `tests/unit/test_dispatch_safe_task_id.py` | Claude review #5 |
| `contract.yaml` YAML corruption fixed | `.superharness/contract.yaml` | Codex/Gemini #1 |

### Commit checklist (before moving to Iteration 1)

- [ ] `git add` all 8 changed/new files above
- [ ] `CHANGELOG.md` entry appended
- [ ] PR title: `fix(core): foundation hardening — daemon, schema, dispatch, gitignore`
- [ ] Verify CI green before merging

---

## Iteration 1 — Layer 2: `shux contract --validate`

**Goal:** Operators and CI can validate the contract on demand without touching the write path. Any YAML parse error or Pydantic schema violation prints a structured report and exits non-zero.

**Files touched:**
- `src/superharness/commands/contract.py` (add `--validate` flag)
- `tests/unit/test_contract_validate.py` (new)

### RED

Write `tests/unit/test_contract_validate.py` with these failing tests (no implementation yet):

```python
def test_validate_clean_contract_exits_zero(tmp_path, monkeypatch):
    # Write a valid minimal contract.yaml, run `shux contract --validate`,
    # assert exit code 0 and stdout contains "OK".

def test_validate_invalid_yaml_exits_nonzero(tmp_path, monkeypatch):
    # Write a syntactically broken YAML, assert exit code 1 and stderr
    # contains "YAML parse error".

def test_validate_schema_violation_exits_nonzero(tmp_path, monkeypatch):
    # Write valid YAML but with acceptance_criteria[0] as a dict (the
    # task-85 pattern). Assert exit code 1 and stderr contains the
    # field path "acceptance_criteria".

def test_validate_missing_contract_exits_nonzero(tmp_path, monkeypatch):
    # No .superharness/contract.yaml present. Assert exit code 1 and
    # message "not found".

def test_validate_reports_all_errors_not_just_first(tmp_path, monkeypatch):
    # Two tasks with invalid fields. Assert both field paths appear in output.
```

Run: `pytest tests/unit/test_contract_validate.py` — all 5 must fail (RED confirmed).

### GREEN

In `src/superharness/commands/contract.py`, add:

```python
def cmd_validate(args) -> int:
    path = _contract_path(args)
    if not os.path.exists(path):
        print(f"[ERROR] contract not found: {path}", file=sys.stderr)
        return 1
    with open(path, encoding="utf-8") as f:
        try:
            doc = yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"[ERROR] YAML parse error: {e}", file=sys.stderr)
            return 1
    try:
        Contract.model_validate(doc)
        print(f"[OK] {path}: valid ({len(doc.get('tasks', []))} tasks)")
        return 0
    except ValidationError as exc:
        print(f"[ERROR] schema violations in {path}:", file=sys.stderr)
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            print(f"  {loc}: {err['msg']}", file=sys.stderr)
        return len(exc.errors())
```

Wire into the `contract` subparser: `--validate` flag or `contract validate` subcommand (pick one, document it).

Run tests — all 5 must pass (GREEN confirmed).

### REFACTOR

- Extract `_load_and_validate_contract(path)` returning `(doc, errors)` so Layer 3b can reuse it.
- Add `--json` output flag for machine-readable error lists (CI integration).
- Update `docs/GUIDE.md` with a `shux contract --validate` entry.

### Acceptance criteria

- `shux contract --validate` exits 0 on a clean contract, non-zero with a human-readable error list on any violation.
- Used in local pre-PR checklist and optionally in CI (`shux contract --validate || exit 1`).
- No changes to the write path.

---

## Iteration 2 — Layer 3b: Centralize `_write_contract` + Warn-Only Validation

**Goal:** Every contract write goes through one function. That function validates the doc against `Contract` and logs a warning if validation fails — but does not block the write. This gives visibility into schema drift without risking availability.

**Why centralize first:** `_write_contract` is currently copied verbatim into 5 modules (`task.py`, `close.py`, `verify.py`, `test_type.py`, `subtask_cancel.py`). Any validation logic added to one copy would be missed by the others. Centralizing is the prerequisite.

**Files touched:**
- `src/superharness/engine/contract_io.py` (new — canonical write + validate)
- `src/superharness/commands/task.py`
- `src/superharness/commands/close.py`
- `src/superharness/commands/verify.py`
- `src/superharness/commands/test_type.py`
- `src/superharness/commands/subtask_cancel.py`
- `tests/unit/test_contract_io.py` (new)

### RED

Write `tests/unit/test_contract_io.py`:

```python
def test_write_valid_contract_succeeds(tmp_path):
    # Write a valid Contract dict via write_contract(). Assert file exists
    # and parses back cleanly. Assert no WARNING logged.

def test_write_invalid_contract_logs_warning_but_writes(tmp_path, caplog):
    # Write a doc with acceptance_criteria[0] as a dict. Assert file is
    # written (no exception), AND caplog contains "schema warning".

def test_write_is_atomic(tmp_path):
    # Assert that a crash mid-write does not corrupt the existing file.
    # (Simulate via monkeypatch of the rename call.)

def test_all_command_modules_import_from_contract_io():
    # Assert that task.py, close.py, verify.py, test_type.py,
    # subtask_cancel.py do NOT define _write_contract locally.
    import ast, pathlib
    for mod in ["task", "close", "verify", "test_type", "subtask_cancel"]:
        src = (pathlib.Path("src/superharness/commands") / f"{mod}.py").read_text()
        tree = ast.parse(src)
        local_defs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        assert "_write_contract" not in local_defs, f"{mod}.py still defines _write_contract"
```

Run tests — all 4 must fail.

### GREEN

Create `src/superharness/engine/contract_io.py`:

```python
import logging
import os
import tempfile

import yaml
from pydantic import ValidationError

from superharness.engine.schemas import Contract

logger = logging.getLogger(__name__)


def write_contract(path: str, doc: object) -> None:
    try:
        Contract.model_validate(doc)
    except ValidationError as exc:
        errs = "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        logger.warning("contract schema warning (write allowed): %s", errs)

    dir_ = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.dump(doc, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

In each of the 5 command modules, delete the local `_write_contract` function and replace call sites with `from superharness.engine.contract_io import write_contract`.

Run tests — all 4 must pass.

### REFACTOR

- Add `read_contract(path)` to `contract_io.py` — returns `(doc, validation_errors)` so callers can branch on health without raising.
- Enable `logger.warning` output to be seen in dashboard (wire into the existing log level config).
- Delete the pre-existing dead copies confirmed by the import test.

### Acceptance criteria

- Only one `_write_contract` implementation exists in the codebase.
- Every contract-modifying command emits a WARNING log on schema drift but does not crash.
- All existing contract-write tests continue to pass.

---

## Iteration 3 — Schema/Data Drift Audit

**Goal:** Know the complete set of validation failures in the live contract before enforcing anything. Iteration 2 adds warning-on-write; this iteration produces the authoritative catalog of what needs to be fixed in Iteration 4.

**Files touched:**
- `tests/unit/test_contract_schema_compliance.py` (new, intentionally failing)
- `docs/drift_audit_report.md` (generated output, gitignored or committed as artifact)

### RED

Write `tests/unit/test_contract_schema_compliance.py`:

```python
import yaml
from pydantic import ValidationError
from superharness.engine.schemas import Contract

def test_live_contract_passes_full_validation():
    """This test is expected to fail until all data drift is fixed (Iteration 4)."""
    with open(".superharness/contract.yaml", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    Contract.model_validate(doc)   # raises ValidationError if any drift remains
```

Run: `pytest tests/unit/test_contract_schema_compliance.py -v` — it MUST fail (currently 1 known error: task 85). This is the canonical RED state for Iterations 3-5.

### GREEN (audit, not fix)

Run the drift collector script to produce the full catalog:

```bash
python3 - <<'EOF'
import yaml
from pydantic import ValidationError
from src.superharness.engine.schemas import Contract

with open(".superharness/contract.yaml") as f:
    doc = yaml.safe_load(f)

tasks = doc.get("tasks", [])
errors_by_task = {}
for i, t in enumerate(tasks):
    try:
        from src.superharness.engine.schemas import ContractTask
        ContractTask.model_validate(t)
    except ValidationError as exc:
        errors_by_task[f"{i}:{t.get('id','?')}"] = exc.errors()

for key, errs in errors_by_task.items():
    print(f"\n--- {key} ---")
    for e in errs:
        loc = ".".join(str(x) for x in e["loc"])
        print(f"  {loc}: {e['msg']} | input={e.get('input','?')!r:.60}")
EOF
```

Document output in `docs/drift_audit_report.md`. Each unique error pattern gets a "fix category":
- `AC_DICT`: `acceptance_criteria` item is a dict, not string
- `STATUS_UNKNOWN`: `status` value not in `TaskStatus` enum
- `MISSING_REQUIRED`: required field absent
- (others as found)

### REFACTOR

Nothing to refactor here — the output is the artifact. The test stays permanently. It should go green after Iteration 4.

### Acceptance criteria

- Full catalog of all drift patterns in `docs/drift_audit_report.md`.
- Every pattern has a fix category and the number of affected tasks.
- `test_live_contract_passes_full_validation` is understood to fail, and the failure matches the catalog exactly.

---

## Iteration 4 — Data Reconciliation

**Goal:** Fix every drift instance identified in Iteration 3 so the live contract passes `Contract.model_validate()` cleanly.

**Files touched:**
- `.superharness/contract.yaml`
- `tests/unit/test_contract_schema_compliance.py` (now passes — GREEN)

### RED

The test from Iteration 3 is already written and failing. That is the RED.

### GREEN (per fix category)

For each category from the drift audit, apply the minimal correct transformation:

**AC_DICT (currently 1 instance — task 85: `feat.headless.auto-approve-policy`):**

The dict `{'support auto_approve_plans': 'true in policy/profile.yaml'}` represents a single criterion whose intent is "support auto_approve_plans: true in policy/profile.yaml". Convert to the string form:

```yaml
acceptance_criteria:
  - "support auto_approve_plans: true in policy/profile.yaml"
```

Rationale: the dict is a YAML serialization artifact (someone used `{key: value}` notation for a single string item). The string form preserves the intent.

**STATUS_UNKNOWN (check for any after TaskStatus enum was extended):**

Query: `grep -n "status:" .superharness/contract.yaml | grep -vE "todo|in_progress|done|plan_proposed|plan_approved|report_ready|review_failed|pending_user_approval|review_requested|stopped|blocked|closed|cancelled|failed|skipped"` — fix any hits to the nearest valid status.

**MISSING_REQUIRED:**

Each case requires individual judgment — do not infer values that were never set. Mark as `status: stopped` with a note in the task's `summary` field if the task has no recoverable state.

After all fixes: `pytest tests/unit/test_contract_schema_compliance.py -v` must pass.

### REFACTOR

- Add `shux contract --validate` to the CI step (now that the live contract is clean, this can be a hard gate).
- Update `docs/drift_audit_report.md` to show all categories as resolved.

### Acceptance criteria

- `Contract.model_validate(doc)` on the live contract returns without error.
- `test_live_contract_passes_full_validation` is green.
- All task data changes are reviewed by the operator (no automated bulk transformations without a diff review).

---

## Iteration 5 — Layer 3a: Strict Pydantic Enforcement on Write

**Goal:** Contract writes that produce schema-invalid output are blocked. Malformed data can no longer enter the contract silently. This is the promoted form of Layer 3b.

**Prerequisite:** Iteration 4 complete. The live contract must pass validation before strict enforcement is turned on — otherwise the first write to any task would be blocked.

**Files touched:**
- `src/superharness/engine/contract_io.py` (change warn to raise)
- `tests/unit/test_contract_io.py` (update the warn test to expect raise)

### RED

Update `test_write_invalid_contract_logs_warning_but_writes` to:

```python
def test_write_invalid_contract_raises(tmp_path):
    # Write a doc with acceptance_criteria[0] as a dict.
    # Assert ContractValidationError (or ValidationError) is raised.
    # Assert no file was written.
```

Run: `pytest tests/unit/test_contract_io.py::test_write_invalid_contract_raises` — fails because `write_contract` currently only warns.

### GREEN

In `contract_io.py`, promote the warning to a raise:

```python
def write_contract(path: str, doc: object) -> None:
    try:
        Contract.model_validate(doc)
    except ValidationError as exc:
        raise ContractValidationError(
            f"Refusing to write contract: {len(exc.errors())} schema violation(s)\n"
            + "\n".join(f"  {'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
        ) from exc
    # ... atomic write as before
```

Define `ContractValidationError(RuntimeError)` in `contract_io.py`.

Run full test suite: `pytest tests/ -q`. Every test that previously relied on warn-and-write must now either produce valid data or be updated to catch `ContractValidationError`.

### REFACTOR

- Add a `SUPERHARNESS_SCHEMA_ENFORCEMENT=warn` env var escape hatch for emergency operator override (logs at CRITICAL, still writes) — document it as a break-glass option only.
- Wire `ContractValidationError` into the CLI error handler so it prints a clean message instead of a traceback.
- Run `shux hygiene` — any hygiene check that writes a task must be tested to produce valid data.

### Acceptance criteria

- `write_contract()` raises on invalid data.
- Operators get a clear error message, not a stack trace.
- The escape hatch exists but is documented as temporary.
- All existing tests pass.

---

## Iteration 6 — Finding #7: Paused-Pid Reconciliation

**Goal:** When a launcher subprocess dies, any inbox item it was driving that is stuck in `paused` status is transitioned to `failed` on the next watcher tick. Agent lanes cannot be permanently wedged by a single crash.

**Context:** `inbox_watch.py` already has zombie-reconcile logic for `running` items with a `pid` field (lines 746-790). `paused` items are not covered by this logic. A paused item with a dead pid blocks the entire agent lane indefinitely.

**Files touched:**
- `src/superharness/commands/inbox_watch.py`
- `tests/unit/test_inbox_paused_reconciliation.py` (new)

### RED

Write `tests/unit/test_inbox_paused_reconciliation.py`:

```python
def test_paused_item_with_dead_pid_transitions_to_failed(tmp_path, monkeypatch):
    # Set up an inbox with one item: status=paused, pid=99999 (guaranteed dead).
    # Run one watcher tick.
    # Assert item status is now "failed" with reason containing "launcher pid disappeared".

def test_paused_item_with_live_pid_stays_paused(tmp_path, monkeypatch):
    # Set up an inbox with one item: status=paused, pid=os.getpid() (self — guaranteed live).
    # Run one watcher tick.
    # Assert item status is still "paused".

def test_paused_item_with_no_pid_stays_paused(tmp_path, monkeypatch):
    # Paused item with no pid field. No transition — ambiguous, do not auto-fail.
    # Assert item status is still "paused".
```

Run: all 3 must fail.

### GREEN

In `inbox_watch.py`, within the tick loop where `paused` items are processed, add after the existing `_ACTIVE` check:

```python
for item in paused_items:
    recorded_pid = item.get("pid")
    if recorded_pid and not _pid_is_running(int(recorded_pid)):
        item["status"] = "failed"
        item["failed_reason"] = f"launcher pid {recorded_pid} disappeared"
        item["failed_at"] = _now_iso()
        _write_inbox(inbox_path, inbox)
        print(f"paused-reconcile: {item.get('task_id')} → failed (pid {recorded_pid} dead)")
```

Reuse the existing `_pid_is_running` helper (already defined at line 57).

Run tests — all 3 must pass.

### REFACTOR

- Consolidate zombie-reconcile (running items) and paused-reconcile into one `_reconcile_dead_pids(inbox)` function to avoid divergence.
- Add metric counter `paused_reconciled_total` to the stats block logged on each tick.
- Add a regression test: two consecutive ticks do not double-transition (idempotent).

### Acceptance criteria

- A paused inbox item with a dead pid is transitioned to `failed` within one watcher tick interval (default 15s).
- A live pid is not affected.
- Operator no longer needs `shux normalize --drop-id-prefix` as a workaround for single-crash lane blocks.

---

## Iteration 7 — PID Schema Split

**Goal:** `daemon.py` and `operator.py` both write to `.superharness/daemon.pid.json` with different key sets. Reads in one module miss keys written by the other. Split into two files with defined schemas.

**Context (from claude_superharness_review.md, Finding #3):**
- `daemon.py:122` writes `{"pid": N}`
- `operator.py:89` writes `{"operator_pid": N, "dashboard_port": N}`
- `daemon.py:90` reads `state.get("pid")` — misses operator-written keys
- Both target `_DAEMON_STATE_FILE = ".superharness/daemon.pid.json"`

**Files touched:**
- `src/superharness/commands/daemon.py`
- `src/superharness/commands/operator.py`
- `.superharness/.gitignore` (add `operator-state.json` if not present)
- `tests/unit/test_daemon_pid_schema.py` (new)

### RED

Write `tests/unit/test_daemon_pid_schema.py`:

```python
def test_daemon_writes_to_daemon_state_file(tmp_path, monkeypatch):
    # Simulate daemon start (mocked subprocess). Assert it writes
    # .superharness/daemon-state.json with key "pid".
    # Assert it does NOT write to daemon.pid.json.

def test_operator_writes_to_operator_state_file(tmp_path, monkeypatch):
    # Simulate operator start. Assert it writes
    # .superharness/operator-state.json with keys "operator_pid" and "dashboard_port".
    # Assert it does NOT write to daemon.pid.json.

def test_daemon_reads_own_state_correctly(tmp_path, monkeypatch):
    # Write a daemon-state.json with pid=12345. Run daemon status check.
    # Assert it correctly reads pid=12345, not None.

def test_operator_reads_own_state_correctly(tmp_path, monkeypatch):
    # Write an operator-state.json with operator_pid=12345, dashboard_port=4000.
    # Assert operator reads both correctly.
```

Run: all 4 fail.

### GREEN

In `daemon.py`:
- Rename `_DAEMON_STATE_FILE = ".superharness/daemon.pid.json"` to `_DAEMON_STATE_FILE = ".superharness/daemon-state.json"`

In `operator.py`:
- Add `_OPERATOR_STATE_FILE = ".superharness/operator-state.json"`
- Update all reads/writes to use `_OPERATOR_STATE_FILE`

Update `.superharness/.gitignore`:
```
operator-state.json
daemon-state.json
```

Run tests — all 4 pass.

### REFACTOR

- Delete `daemon.pid.json` from `.gitignore` (it is replaced by the two new files).
- Add a migration note in `CHANGELOG.md`: operators with existing `daemon.pid.json` should run `shux daemon stop && shux daemon start` once to regenerate.
- Define `DaemonState(BaseModel)` and `OperatorState(BaseModel)` in `schemas.py` for the two schemas (typed reads, no silent None returns).

### Acceptance criteria

- `daemon.py` and `operator.py` read and write disjoint files.
- `shux daemon status` and `shux status` both report correct pids after the split.
- No references to the old `daemon.pid.json` remain in source (grep check).

---

## Execution Order and Branch Strategy

```
Iteration 0  →  PR: fix/foundation-hardening
Iteration 1  →  PR: feat/contract-validate-cmd
Iteration 2  →  PR: refactor/centralize-write-contract
Iteration 3  →  PR: chore/drift-audit (docs only, no code)
Iteration 4  →  PR: fix/contract-data-reconciliation
Iteration 5  →  PR: feat/strict-contract-enforcement
Iteration 6  →  PR: fix/paused-pid-reconciliation
Iteration 7  →  PR: fix/pid-schema-split
```

Each PR is independent after the one before it merges. Iterations 3 and 4 must be sequential (audit before reconcile). Iteration 5 must follow 4 (data clean before enforcement). All others are parallelizable if bandwidth allows.

**Feature freeze policy:** No new feature PRs while Iterations 0-3 are open. Iterations 4-7 can land alongside features once the foundation is stable.

---

## Test Coverage Targets

| Iteration | New tests | Must pass before merge |
|---|---|---|
| 0 | 5 (dispatch sanitization — already written) | Yes |
| 1 | 5 (validate subcommand) | Yes |
| 2 | 4 (contract_io module) | Yes |
| 3 | 1 (compliance — intentionally failing, documents RED) | RED must be documented |
| 4 | 0 new (existing compliance test turns green) | Yes |
| 5 | 1 (strict raise) | Yes |
| 6 | 3 (paused reconciliation) | Yes |
| 7 | 4 (pid schema split) | Yes |

---

## Known Non-Goals

- **Removing the Pydantic model entirely**: not on the table. The model is the right design; it needs to be wired in, not removed.
- **Migrating from YAML to a binary format**: deferred. File-native protocol is the design choice. Fix the schema before questioning the storage format.
- **Automated bulk-fix of contract data**: data reconciliation (Iteration 4) requires operator review of each change, not a script that silently transforms 94 tasks.
- **Paused-pid reconciliation via aggressive kill**: do not send signals to paused pids. Only check liveness (`os.kill(pid, 0)`). Forcibly killing a dispatch subprocess is out of scope.
