# Plan: enqueue/dispatch gate parity + owner-mismatch guard

**Status:** implemented (v1.24.x — engine/lifecycle.py, inbox_enqueue.py, delegate.py EXIT_PERMANENT_BLOCK; regression tests v1.24.12)
**Date:** 2026-04-15
**Author:** claude-code (synod session)
**Scope:** `src/superharness/commands/inbox_enqueue.py`, `src/superharness/commands/delegate.py`

---

## Problem

Observed in `synod` project (2026-04-15T17:12–17:15Z):

1. `shux delegate iter-0-red --to claude-code` succeeded and enqueued the task.
2. Launcher picked it up ~12s later and failed with:
   `blocked: task 'iter-0-red' status is 'todo' — plan must be approved before delegating`
3. Inbox recorded `status: failed, retry_count: 1/3`. Same sequence repeated for `iter-0`.

Two defects surfaced:

### Defect A — gate asymmetry between enqueue and dispatch

`inbox_enqueue.py:33` blocks only `{plan_proposed, done}`:

```python
ENQUEUE_BLOCKED_STATUSES = {"plan_proposed", "done"}
```

But `delegate.py:649` (gate 4) computes allowed statuses per workflow. For `implementation` workflow the allowed set is `{plan_approved, in_progress, report_ready, review_passed, review_failed, pending_user_approval}` (`delegate.py:307-314`) plus terminal `{done, failed, stopped}`. `todo` is not in either set, so dispatch rejects.

Net effect: enqueue accepts a task that dispatch will reject, creating failed inbox entries that retry up to `max_retries`. For the synod case this means 3 wasted launcher cycles per delegation.

### Defect B — no owner-mismatch check

Contract has `owner: codex-cli` for `iter-0-red` but the command accepted `--to claude-code` without warning. The command `shux delegate <id> --to <agent>` silently rewrites the dispatch target. The user likely wants either:
- a hard block if `--to` contradicts `owner`, OR
- a confirmation prompt, OR
- at minimum a visible warning on stderr

Current behaviour: silent accept.

---

## Proposed patch

### Part 1 — tighten `_validate_contract` in `inbox_enqueue.py`

Replace the static `ENQUEUE_BLOCKED_STATUSES` check with a workflow-aware check that mirrors `delegate._allowed_statuses_for_workflow`. Import the helper; reject at enqueue time whatever dispatch would reject.

**RED** — add failing tests:
- `tests/unit/test_inbox_enqueue.py::test_enqueue_rejects_todo_for_implementation`
- `tests/unit/test_inbox_enqueue.py::test_enqueue_accepts_todo_for_quick_workflow`

**GREEN** — implementation:
```python
# inbox_enqueue.py
from superharness.commands.delegate import (
    _allowed_statuses_for_workflow,
    _infer_workflow,
)

TERMINAL_STATUSES = {"done", "failed", "stopped"}

def _validate_contract(contract_file, task_id, project_dir):
    ...
    status = str(task.get("status", ""))
    workflow = _infer_workflow(task_id, task)
    allowed = _allowed_statuses_for_workflow(workflow, for_review=False)
    if status not in allowed and status not in TERMINAL_STATUSES:
        _abort(
            f"blocked: task '{task_id}' status is '{status}' for workflow '{workflow}'.\n"
            f"  allowed at enqueue: {', '.join(sorted(allowed))}\n"
            f"  hint for implementation: propose and approve a plan first "
            f"(shux task status --id {task_id} --status plan_proposed ...)"
        )
```

**REFACTOR** — move the helpers `_infer_workflow` and `_allowed_statuses_for_workflow` out of `delegate.py` into a shared module (e.g. `superharness/engine/lifecycle.py`) so neither command depends on the other.

### Part 2 — owner-mismatch guard in `enqueue_cmd`

Add a check after contract is loaded:

**RED** — tests:
- `test_enqueue_blocks_owner_mismatch_by_default`
- `test_enqueue_allows_owner_mismatch_with_force_flag`

**GREEN**:
```python
# enqueue_cmd signature gains force_reassign: bool = False
owner = str(task.get("owner", "") or "").strip()
if owner and owner != target:
    if not force_reassign:
        _abort(
            f"blocked: task '{task_id}' is owned by '{owner}', not '{target}'.\n"
            f"  To dispatch to a different agent, pass --force-reassign or update contract.yaml.",
            code=1,
        )
    print(
        f"Warning: reassigning '{task_id}' from owner '{owner}' to '{target}'.",
        file=sys.stderr,
    )
```

Wire `--force-reassign` through the CLI router (`main` at `inbox_enqueue.py:191`).

### Part 3 — non-retryable launcher failures

Independent of enqueue gating, the launcher should not retry a dispatch that failed gate-4 (a static lifecycle violation will fail identically on every retry). Tag such failures as non-retryable so `retry_count` does not climb to 3.

**Location:** wherever the launcher maps `delegate` exit codes to inbox status. Introduce a sentinel exit code (e.g. `exit 2`) from `delegate.py` for "permanent block" vs generic `exit 1` for transient errors.

**RED** — test:
- `test_launcher_marks_failed_with_no_retry_on_exit_2`

**GREEN** — in `delegate.py` gate 4, `return 2` instead of `return 1`. In the launcher, treat exit 2 as terminal (`retry_count = max_retries`, no further attempts).

---

## Test plan

All three parts are covered by unit tests. Additionally add one integration test:
- `tests/integration/test_synod_regression.py::test_todo_task_cannot_be_enqueued` reproducing the exact synod failure and asserting `shux delegate` exits 1 with a clear message before ever writing to `inbox.yaml`.

Run:
```bash
pytest tests/unit/test_inbox_enqueue.py tests/unit/test_delegate.py -q
pytest tests/integration/test_synod_regression.py -q
```

---

## Risks / open questions

1. **Helper extraction (part 1 refactor)** may touch several test files that currently import from `delegate`. Keep thin re-exports in `delegate.py` for one release to avoid breaking downstream.
2. **`--force-reassign` semantics** — should reassigning also rewrite `owner` in `contract.yaml`, or only override for one dispatch? Proposal: one-shot override, do not mutate contract. Confirm with operator.
3. **Exit-code change** (part 3) is a soft contract change for any external tooling that parses launcher logs. Audit `.superharness/launcher-logs` consumers before merging.
4. **Backward compat** — projects with tasks sitting at `todo` expecting delegate to bounce them will now fail earlier. That is the desired behaviour but should be called out in `CHANGELOG.md`.

---

## Out of scope

- Redesigning the lifecycle itself (plan → approved → dispatch).
- Watcher/retry policy beyond the exit-code change.
- UI changes in `shux status` / monitor.
