# Design: Ship Step in Task Lifecycle

**Status:** proposed
**Date:** 2026-04-18
**Task:** feat.task-lifecycle-ship
**Author:** claude-code

---

## Problem

When an agent completes a task and writes `report_ready`, a human must manually
run `/ship` to commit, push, and open a PR. This is friction: the agent did the
work, but the operator becomes a required middleman for a mechanical handoff.

The goal is to let the task lifecycle extend through the git/PR boundary so an
agent can own its own ship step — while keeping all security and quality gates
intact.

### Why not do this naively (the bug analysis)

A simple "auto-commit on report_ready" would bypass the 17-step `/ship` pipeline:
- ShipGuard SAST scan
- pytest / test suite
- doc sync (README, GUIDE.md, adapter specs)
- CHANGELOG append check
- Sensitive-data sanitization
- CI gate verification

None of these are optional. An agent that commits without running them produces
unreviewed, potentially insecure output. This is the core reason the task was
originally blocked.

---

## Design

### Principle: agent runs /ship, not the harness

The harness does not invent a new auto-commit mechanism. Instead the agent is
instructed to run `ALLOW_PUSH=1 /ship commit` as the final step of its task,
inside its dispatch worktree, before writing `report_ready`.

This means:
- Every existing `/ship` gate runs exactly as it does for a human operator.
- The harness adds only two things: (1) a new lifecycle status `pr_open` for
  tracking, and (2) a dispatch flag `ship_on_complete` to opt in.

### New lifecycle status: `pr_open`

```
todo → plan_proposed → plan_approved → in_progress → report_ready → pr_open → done
```

`pr_open` signals that the agent has run `/ship commit` and a PR is open.
The operator reviews the PR on GitHub, merges it, and closes the task. No new
automation needed at this phase — the existing GitHub merge + auto-release
workflow handles the rest.

`pr_open` is valid only on the `implementation` workflow. Quick and note tasks
skip it (no PR required).

### Opt-in flag: `ship_on_complete`

Add `ship_on_complete: true` to a contract task to activate the ship step.
Default is `false` — existing tasks are unaffected.

```yaml
- id: feat.my-feature
  status: plan_approved
  workflow: implementation
  ship_on_complete: true
```

When `ship_on_complete: true`, the dispatch prompt instructs the agent:

> After writing report_ready, run `ALLOW_PUSH=1 /ship commit` (non-interactive).
> If /ship commit exits non-zero, do NOT write report_ready — write a failed
> handoff instead and exit. The harness will retry or surface the failure.

If the agent writes `report_ready` without opening a PR (e.g., `/ship commit`
failed silently), the watcher sets status to `failed` after a grace period.

---

## Risk Analysis

### 1. Review pipeline bypass

**Risk:** agent commits without running security scan, tests, or doc sync.

**Mitigation:** the agent runs `/ship commit` — the same entrypoint a human
uses. `/ship commit` calls `ship-check` (ShipGuard, pytest, doc sync, CHANGELOG)
before staging a single file. If any gate fails, `/ship commit` exits non-zero
and the agent writes a failed handoff instead of `report_ready`.

No new bypass surface is introduced. The agent can only succeed the ship step
by passing every existing gate.

### 2. Mixed commits

**Risk:** agent stages changes unrelated to the task (e.g., leftover edits from
a prior run).

**Mitigation:** dispatch already creates an isolated worktree (`feat.dispatch-auto-stash`,
shipped v1.x). The worktree contains only the files the agent touched during this
dispatch. Unrelated changes in the main working tree are stashed before dispatch
and popped after. The agent's `/ship commit` operates on the worktree — no
ambient state bleeds in.

Additional guard: the dispatch prompt specifies `git add <explicit files>` from
the task's `files_touched` list. `/ship commit` refuses `git add -A`.

### 3. Concurrent agent conflicts

**Risk:** two agents dispatch simultaneously, both try to push to the same
branch, conflict.

**Mitigation:** each dispatch gets a unique feature branch derived from the task
ID (e.g., `feat/my-feature-<short-sha>`). Branch names are task-scoped; two
agents on different tasks never share a branch. Two agents on the same task
cannot both be `in_progress` simultaneously — the second dispatch is blocked by
the gate (status must be `plan_approved`, not `in_progress`).

### 4. Hook failures

**Risk:** pre-commit or pre-push hooks fail inside the dispatch worktree; agent
silently succeeds or hangs.

**Mitigation:** dispatch runs with `NON_INTERACTIVE=1`. Hooks that prompt are
either skipped (safe: e.g., changelog confirmation) or cause the command to
exit non-zero (unsafe hooks should never prompt in CI-mode). A hook failure
produces a non-zero exit from `/ship commit`, which the agent treats as failure
and writes a failed handoff. The harness retries up to `max_retries` then marks
the task `failed`.

The dispatch timeout (`DISPATCH_TIMEOUT_SECONDS`, default 1800) provides a
ceiling for hung hooks.

---

## Implementation Plan (future, not in scope of this doc)

### Phase 1 — Lifecycle status (low risk)

1. Add `pr_open` to `allowed_statuses_for_workflow("implementation")` in
   `engine/lifecycle.py`.
2. Add `pr_open` to the contract schema in `engine/contract_schema.py`.
3. Teach monitor UI to render `pr_open` with a GitHub PR badge.
4. No dispatch change needed — `pr_open` tasks are not re-dispatched.

Tests: add `pr_open` to unit tests in `test_lifecycle.py` and
`test_contract_schema.py`.

### Phase 2 — `ship_on_complete` flag (medium risk)

1. Add `ship_on_complete: bool` field to `ContractTask`.
2. In the dispatch prompt builder (`orchestrator.py`), append the ship
   instruction when `ship_on_complete=True`.
3. In the post-dispatch watcher, if `ship_on_complete=True` and status is
   `report_ready` with no PR URL in the handoff, set status to `failed`
   (missing PR check).
4. Add `--ship-on-complete` flag to `shux delegate`.

Tests: unit tests for prompt injection, watcher behaviour, missing-PR guard.

### Phase 3 — PR URL tracking (low risk)

Store the PR URL in the handoff `outcomes` list so the monitor can render a
direct link. No schema change needed — outcomes is a freeform list already.

---

## Out of scope

- Auto-merge after PR approval (too much automation risk without human review).
- Triggering `/ship-release` from the lifecycle (tag + publish remain manual).
- Changing the review pipeline itself.
- Any change to the `quick` or `note` workflows.

---

## Decision: recommended approach

Adopt Phase 1 now (pure status addition, zero dispatch risk). Gate Phase 2
(`ship_on_complete`) behind explicit operator opt-in per task. Never auto-enable
for existing tasks. Validate Phase 2 on one synthetic task in the superharness
repo itself before enabling for other projects.

The auto-stash interim (shipped) proved sufficient to avoid working-tree
contamination — Phase 2 builds on it rather than replacing it.
