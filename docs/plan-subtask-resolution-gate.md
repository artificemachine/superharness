# Plan: `shux close` subtask-resolution gate + `cancelled` status

**Status:** proposed
**Owner:** claude-code
**Date:** 2026-04-21
**Related:** `.superharness/contract.yaml` task `feat.subtask-resolution-gate` (to be created)

---

## Problem

`shux close` and `shux task status --status done` succeed even when a task's
subtasks are still `pending` or `in_progress`. Subtasks are supposed to reflect
the agent's decomposition of a task, but there is no enforcement that they were
resolved, so the contract lies: a "done" task can silently carry half-finished
sub-work.

Two things are missing, and shipping either one alone is worse than shipping
nothing:

- A **gate** that refuses to close a parent whose subtasks are still open.
- A **vocabulary** for retiring a subtask that was planned but became
  unnecessary, so the gate does not force agents to fake-complete work.

Without `cancelled`, agents are forced to either mark unnecessary subtasks
`done` (lying) or leave them open forever (permanent false signal). The gate
without the escape hatch creates a trap. Both pieces are needed together.

## Non-goals

- No new dispatch or execution semantics for subtasks. They remain planning
  artifacts written by `shux delegate --orchestrate`; this change only affects
  how the parent task is allowed to transition to `done`.
- No cascade from top-level task cancellation — out of scope for v1 of this
  feature, see "Open questions" below.
- No change to how Morpheme renders subtasks. Adapter-payload schema bump is
  covered only if the `status` field is already in the payload; otherwise
  deferred.

## Verified current state

| Area | File | Today | After |
|---|---|---|---|
| Status enum | `src/superharness/engine/schemas.py:57` | `pending \| in_progress \| done \| failed` | add `cancelled` |
| Close gate | `src/superharness/commands/close.py:72` | checks parent status only | also checks subtasks when opted in |
| Status-set gate | `src/superharness/commands/task.py` (status=done path) | no subtask check | mirrors close gate |
| Enum test | `tests/unit/test_subtask_schema.py:78` | asserts `cancelled` is **rejected** | flip: asserts `cancelled` is **accepted** |
| Subtask resolver | `src/superharness/engine/subtask.py:33` | returns explicit status or inherits | pass through `cancelled` as terminal |
| Profile loader | `src/superharness/commands/workflow_cmd.py:44` | exists for `workflow` field | reused for `require_subtask_resolution` |
| Hygiene | no subtask check today | n/a | add "closed tasks with open subtasks" warning |
| Cancel command | n/a | n/a | new: `shux subtask cancel` |

## Design decisions (locking these in before code)

### D1. Open vs resolved states

Decision: for the purposes of the gate, subtask statuses partition as follows:

| Status | Gate says |
|---|---|
| `pending`, `in_progress` | **open** — blocks parent close |
| `done`, `cancelled` | **resolved** — allows parent close |
| `failed` | **open** — blocks parent close (failure is not resolution) |

Rationale: `failed` means "this subtask attempted work and did not succeed." A
parent cannot be legitimately `done` if a planned sub-step failed. If the
failure is acceptable (the work is no longer needed), the agent cancels it
explicitly; if it is a genuine failure, the parent should not close. This
keeps `cancelled` as the only explicit way to retire open sub-work and avoids
overloading `failed`.

### D2. Profile vs task precedence

Decision: **profile wins when profile sets `true`; task can opt in but not out.**

```
effective_gate = profile.require_subtask_resolution OR task.require_subtask_resolution
```

Rationale: profile is the org-level floor. An agent should not be able to
downgrade a governance setting per task. A task can tighten (opt in even when
the profile is off), but not loosen.

### D3. The escape hatch is `--cancel-remaining`, not `--force`

Decision: introduce `--cancel-remaining --reason "..."` on `shux close` and
`shux task status --status done`. Keep `--force` strictly for emergency
ledger-integrity bypass (it already exists for the status lifecycle gate;
extend its scope to the subtask gate with the same warning semantics).

```bash
# Normal close — fails if subtasks open
shux close --id T-42

# Ack unresolved subtasks, then close, with a single shared reason
shux close --id T-42 --cancel-remaining --reason "scope shrunk after review"

# Emergency (logged loudly, discouraged)
shux close --id T-42 --force
```

Rationale: `--force` without `--cancel-remaining` leaves subtasks permanently
open on a closed parent. That is exactly the dangling state the feature exists
to prevent. `--cancel-remaining` is atomic, writes per-subtask ledger entries
with a shared reason, and keeps the contract self-consistent.

### D4. Cascade on parent cancel — deferred

Decision: **defer**. For v1, closing/cancelling a parent does not cascade to
subtasks. `shux hygiene` will surface the dangling state as a warning so it
does not hide silently. Revisit once real usage tells us the right shape
(auto-cancel with inherited reason vs recursive gate).

### D5. Ledger format

Every cancellation writes exactly one line:

```
- 2026-04-21T14:03:11Z — claude-code — SUBTASK_CANCEL: T-42.3 (parent=T-42) — <reason>
```

Bulk cancellation via `--cancel-remaining` writes one line per subtask, plus
the existing `CLOSE:` line for the parent. Reason is required and is
propagated to each line verbatim so the audit trail survives.

---

## Rollout order — ship in four PRs, not one

Shipping all four pieces at once bundles a vocabulary change, a policy
change, a new command, and a passive check. If something breaks flow, we
cannot tell which piece caused it. Ship in order:

1. **PR 1: `cancelled` status + schema update** (vocabulary, no policy)
2. **PR 2: `shux subtask cancel` command** (uses new vocabulary, still no gate)
3. **PR 3: hygiene warning "closed tasks with open subtasks"** (passive signal — lets real usage surface the problem before the gate fires)
4. **PR 4: the gate** (`require_subtask_resolution` + `--cancel-remaining`) — enabled only per-task/profile opt-in, default off

Between PR 3 and PR 4, leave at least one active session. If hygiene surfaces
real cases in the wild, it validates the gate before enabling it. If it finds
nothing, we learn the problem is rarer than expected and can right-size the
gate's ergonomics.

---

## TDD plan per PR

### PR 1 — `cancelled` status

**Red**
- Flip `tests/unit/test_subtask_schema.py::TestSubtask::test_invalid_status_raises`
  to a **positive** test: `cancelled` validates successfully.
- Add `tests/unit/test_subtask_schema.py::TestSubtask::test_cancelled_is_terminal`
  asserting `SubtaskStatus.cancelled == "cancelled"` and enum membership.
- Add a resolver test in `tests/unit/test_subtask_resolver.py`: explicit
  `cancelled` on a subtask with an in-progress parent resolves to `cancelled`
  (does not get overridden by parent inheritance).

**Green**
- Add `cancelled = "cancelled"` to `SubtaskStatus` in `src/superharness/engine/schemas.py`.
- Extend `resolve_subtask_status` in `src/superharness/engine/subtask.py` to
  treat explicit `cancelled` as terminal (same precedence rules as other
  explicit statuses, which already win over inheritance — likely a no-op
  after reading the logic, but verify the test proves it).

**Refactor**
- Consolidate the "resolved" predicate into one helper:
  `is_subtask_resolved(status: str) -> bool` that returns `True` for
  `{done, cancelled}`, used by the later hygiene check and the gate. Avoids
  three scattered definitions.

**Acceptance**
- All existing subtask tests green.
- YAML round-trip on a contract with a `cancelled` subtask works.

### PR 2 — `shux subtask cancel`

**Red**
- `tests/unit/test_subtask_cancel_command.py` (new):
  - cancels a subtask by id, sets `status=cancelled`
  - writes a ledger line in the documented format
  - refuses with a non-zero exit when the subtask is not found
  - refuses with a non-zero exit when `--reason` is missing
  - refuses when the subtask is already `done` (cannot cancel completed work)
  - permits cancelling from `pending`, `in_progress`, `failed`

**Green**
- New `src/superharness/commands/subtask_cancel.py` following the shape of
  `close.py` (load contract → mutate → atomic write → ledger append).
- Wire into `src/superharness/cli.py` as `shux subtask cancel`.

**Refactor**
- If the contract load/atomic-write idiom in `close.py` is close enough to
  warrant a shared helper, extract it — but only if PR 1 already did not, to
  keep this PR focused.

**Acceptance**
- CLI help shows the command.
- `shux hygiene` (unchanged) continues to pass.
- Ledger line matches the format above.

### PR 3 — hygiene warning

**Red**
- `tests/unit/test_hygiene_subtask_dangling.py` (new):
  - contract with a `done` parent and an open subtask emits a warning
  - contract with a `done` parent and all-resolved subtasks is clean
  - contract with an in-progress parent and open subtasks is clean (gate is
    about closed parents with dangling subtasks, not the other direction)

**Green**
- Extend the hygiene command (whichever module implements `shux hygiene` —
  locate via `grep -l "def.*hygiene"`; `commands/adapter_payload.py` is not
  it, likely `commands/status.py` or a dedicated module).
- Use `iter_all_tasks` and the new `is_subtask_resolved` helper.

**Refactor**
- If hygiene has grown several inline predicates, consider extracting each
  check into a small function. Only if the file has become large enough to
  justify it — don't preemptively refactor.

**Acceptance**
- Warning is non-blocking (exit 0) — this is a signal, not a gate.
- Format matches existing hygiene output conventions.

### PR 4 — the gate

**Red** — covers both `shux close` and `shux task status --status done`:
- gate off (default): open subtasks do not block close
- gate on via task field: open subtasks block close with actionable error
- gate on via profile: task field false still triggers gate (profile wins)
- gate on, task field true, profile false: gate triggers
- `--cancel-remaining --reason "X"` cancels every open subtask with reason X,
  writes N ledger lines + CLOSE line, then closes successfully
- `--cancel-remaining` without `--reason`: error, nothing mutated
- `--force` alone bypasses the gate but logs a loud warning to ledger
- `failed` subtask blocks close (D1)

**Green**
- `close.py`:
  - read `require_subtask_resolution` from task and profile; OR-combine
  - when enabled and not `--force`, iterate subtasks and fail on any
    unresolved one; error message names each offending subtask
  - implement `--cancel-remaining` as: for each open subtask, call the
    same internal helper introduced in PR 2; then proceed to close
  - all mutation remains in one atomic contract write
- `task.py` status-set path: same logic, factored into a shared helper so
  the two entry points cannot drift.

**Refactor**
- Extract `_evaluate_subtask_gate(task, profile) -> GateResult` returning
  the effective policy + list of offending subtasks. Both close and status
  paths consume it identically.

**Acceptance**
- Default behavior unchanged: every existing test passes.
- Opting in produces an actionable error that names the offending subtasks
  and the two ways out (`--cancel-remaining --reason` or resolve them).
- Ledger is self-consistent after every exit path (success, blocked, bulk
  cancel, force).

---

## Backward compatibility

- `require_subtask_resolution` defaults to `false` everywhere. Zero migration
  burden for existing projects.
- The schema change (adding a new enum variant) is additive. Old contracts
  parse. Old CLI versions reading a contract that contains a `cancelled`
  subtask will fail validation — acceptable because subtask schema is internal
  to superharness, not a public API, and a minor version bump is warranted.
- Minor version bump: PR 1 lands `1.29.0` (new enum variant). PR 4 lands
  `1.30.0` (new policy field + new flags). PRs 2 and 3 are patch bumps.

## Risks

- **Flipping the existing `test_invalid_status_raises` test is a semantic
  change** — callers who validated input against "cancelled is invalid" will
  silently accept it. Grep for `"cancelled"` across the codebase before
  landing PR 1; none expected, but verify.
- **Profile-wins precedence is opinionated.** If a user expects "my task says
  false, so gate is off," they will be surprised. Document explicitly in the
  error message: _"gate enabled by project profile; cannot be disabled per
  task."_
- **`--cancel-remaining` atomicity.** If the contract write succeeds but
  ledger append fails, we have a state drift. Current code already tolerates
  ledger append failures with a warning — acceptable, same as the existing
  close path. Do not raise this bar in this PR.

## Open questions

- Cascade on parent cancel (D4 — deferred). Revisit after 2–4 weeks of real
  usage data from PR 3's hygiene warning.
- Should `shux subtask status` surface a new `cancelled` badge in the
  dashboard UI? Yes, but that is a dashboard concern tracked separately;
  this plan only guarantees the state is representable and readable.
- Does adapter-payload need a schema bump to carry `cancelled`? If the
  payload exposes subtask status, yes — check `docs/adapter-payload-spec.md`
  during PR 1 and bump if so.

## Acceptance criteria (whole feature)

1. `SubtaskStatus` enum includes `cancelled`.
2. `shux subtask cancel --task T --sub S --reason "..."` marks a subtask
   cancelled and writes a ledger line.
3. `shux hygiene` warns on any `done` parent that has an open subtask.
4. With `require_subtask_resolution: true` on either task or profile,
   `shux close` and `shux task status --status done` refuse to close when a
   subtask is open, and the error names each offending subtask.
5. `--cancel-remaining --reason "..."` cancels every open subtask with the
   shared reason, then closes the parent, in one atomic contract write plus
   a consistent ledger tail.
6. Default behavior is unchanged for projects that do not opt in.
7. Full test suite green on every PR.
