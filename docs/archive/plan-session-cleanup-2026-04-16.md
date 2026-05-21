# Plan: session cleanup — post v1.24.1

**Status:** proposed
**Date:** 2026-04-16
**Author:** claude-code (session ccg-shux-version-1.24.0-wip)
**Scope:** finish this session cleanly; defer the Morpheme UI consumption to its own session

---

## Context

Over this session, superharness shipped four minor releases and one hotfix:

| Version | What landed | Merged |
|---|---|---|
| 1.21.0 | Consolidated blocked_by normalization + generic adapter-preview rename | PR #97 |
| 1.22.0 | Dashboard "Propose Plan" owner-authored modal, inline hints, gated-Enqueue tooltip | PR #98 |
| 1.23.0 | Gate parity, `--plan-only` dispatch, exit-2 permanent block, Dashboard "Delegate Plan" | PR #99 |
| 1.24.0 | `resolved_model {id, label}` per task + subtask, schema v1.1, adapter manifest schema bump, codex-cli re-mapped | PR #100 |
| 1.24.1 | Packaging regression: `adapter_manifests/*.yaml` missing from wheel | PR #101 |

Everything is merged, tagged, released, and on PyPI. `shux --version` = 1.24.1 locally.

Four loose ends remain on superharness before the session can end cleanly:

1. **Pre-session stashed drift.** `.superharness/contract.yaml` and `src/superharness/adapters/claude-code/hooks/branch-guard.sh` arrived modified at session start and have been riding along in `git stash` through every branch switch.
2. **Open backlog task in contract.** `feat.adapter-payload-resolved-model` shipped (v1.24.0 + v1.24.1) but is still `todo` in `.superharness/contract.yaml`, plus there is 1 paused inbox item for it from an earlier auto-dispatch attempt.
3. **Chronic CI flake.** `tests/unit/test_benchmark_models.py::test_benchmark_models_shows_usage` has failed every PR in this session on ubuntu + macOS + windows. Each merge used `gh pr merge --admin` to override it. That habit is dangerous — the next real regression will get reflexively overridden.
4. **Morpheme UI consumption.** `resolved_model.label` ships unused until Morpheme renders it. That is the point of v1.24.0. But it lives in a different repo and deserves its own focused session.

---

## Proposal

### Step 1a — Rename Morpheme remote references (done 2026-04-16)

Morpheme repo migrated from `celstnblacc/morpheme` → `artificemachine/morpheme`.
Updated inline in this session before the cleanup PR:

- `CLAUDE.md` (1 line, authorized)
- `AGENTS.md` (1 line, authorized)
- `docs/morpheme-branch-policy.md` (2 mentions)
- `docs/plan-session-cleanup-2026-04-16.md` (this file, 3 mentions)

`celstnblacc/superharness` refs remain untouched — only the Morpheme repo
moved.

### Step 1 — Resolve the stashed drift (~10 min)

**Scope:** `.superharness/contract.yaml`, `src/superharness/adapters/claude-code/hooks/branch-guard.sh`

**Actions:**
- Inspect `git stash show -p` for both files.
- For each: decide whether the change is real work that should land, or incidental drift that should be discarded.
- Land real changes on a small branch with a descriptive commit message; discard drift with `git checkout --` on the file.
- Drop all stashes from this session.

**Why:** stashes riding along across multiple branches are a vector for silent loss. Leaving them makes the next session open on an unclear state.

### Step 2 — Close out `feat.adapter-payload-resolved-model` (~2 min)

**Scope:** `.superharness/contract.yaml`, `.superharness/inbox.yaml`, a `done` handoff YAML

**Actions:**
- Transition contract task `feat.adapter-payload-resolved-model` from `todo` to `done`. Record `done_at`, `done_by`, `verified`, `verified_by`, `tests_passed: true`.
- Remove the 1 paused inbox item for this task (from the earlier auto-dispatch attempt).
- Write a `done` handoff under `.superharness/handoffs/` noting the feature shipped in v1.24.0 + v1.24.1, linking both PRs.

**Why:** the task is delivered. Leaving it `todo` in the contract misrepresents project state and keeps the dashboard noisy.

### Step 3 — Fix the `test_benchmark_models_shows_usage` flake (~30 min)

**Scope:** `tests/unit/test_benchmark_models.py`, possibly `src/superharness/engine/benchmark.py` if a small hook is needed

**RED** — tests currently fail because the test asserts that `benchmark_models()` output contains "model", "opus", or "sonnet", but the fixture has no dispatch data within the last 7 days. The assertion sees the fallback message "no dispatch data in the last 7 days."

**GREEN** — two plausible fixes, either works:
- **A.** Mock `datetime.now()` / `_now_utc()` so "now" falls inside the test's seeded 7-day window.
- **B.** Seed the test's dispatch data with a timestamp generated from the test's mocked `now`, so the 7-day window always covers the fixture.

Prefer B — mocking time globally is brittle. The fixture already controls the data; it can control the timestamp.

**REFACTOR** — if the benchmark module uses a naked `datetime.now()` call, consider extracting `_now_utc()` as a module-level indirection so future tests can override it cleanly.

**Acceptance:** run `pytest tests/unit/test_benchmark_models.py -q` three times in a row; all pass. Run on CI for one sample PR; all three OS runners pass.

**Why:** the admin-override habit is compounding risk. A real regression that happens to land on the same PR as this flake would be merged without anyone noticing. Cheap to fix, high value in the CI signal.

### Step 4 — Deferred: Morpheme UI consumption

**Not this session.** Scope lives on `artificemachine/morpheme` at branch `feat/superharness-integration-morpheme`. Separate working context, 1–2 h of UI work. Leave a handoff note at the end of this session pointing to it.

**What it will do:**
- Render `resolved_model.label` on task/subtask cards in the Morpheme UI.
- Fall back to `model_tier` string when the field is absent (schema < 1.1).
- Remove the tier-only badge renderer once schema 1.1+ is the baseline.

---

## Commit / release strategy

Three options, from least to most overhead:

**A.** One PR bundling steps 1 + 2 + 3. One version bump to `1.24.2` (patch: flaky-test fix is the only user-visible change; steps 1 and 2 are pure hygiene). **Recommended.** ← default

**B.** Separate PRs per step. Overkill for work of this size.

**C.** Skip the version bump and commit directly on main. Violates the project rule that every merge goes via PR. Rejected.

### Acceptance criteria for the combined PR

- [ ] Stashes resolved; `git stash list` has no entries from this session.
- [ ] Contract task `feat.adapter-payload-resolved-model` shows `done`.
- [ ] Inbox has 0 paused items for that task.
- [ ] `done` handoff YAML exists.
- [ ] `pytest tests/unit/test_benchmark_models.py -q` passes three consecutive local runs.
- [ ] CI Tests job is green on all three OS runners for the first time this session.
- [ ] `pyproject.toml` + `CHANGELOG.md` + tag bump to `1.24.2`.

---

## Out of scope

- Morpheme UI rendering of `resolved_model.label` — separate session on `artificemachine/morpheme`.
- Rewriting the auto-dispatch logic that enqueued `feat.adapter-payload-resolved-model` unexpectedly. Its behavior was correct given the contract state; the task was genuinely `todo`. This will stop happening after step 2 flips the status.
- Any other CI flakes. Only this one has been reproducibly failing every PR.

---

## Risks / open questions

1. **Stashed `branch-guard.sh` drift** — if the drift is a real fix the user is mid-way through, discarding it is lossy. Verify before dropping. Default: show the user `git stash show -p stash@{0}` and ask if unsure.
2. **Benchmark-test fix may not be one-liner.** If the test's fixture is structured in a way that doesn't accept injected timestamps, plan grows. Budget 45 min with a 15 min check-in; escalate if I'm still debugging at 45 min.
3. **Version bump classification.** Flaky-test fix is arguably a `chore` not a `fix`. Going with `fix` because CI reliability is user-facing (anyone running `pytest tests/` on their machine hit this). Bikeshed acceptable — user can downgrade to chore when approving.

---

## TDD cycle (applied to step 3)

- **RED** — reproduce the flake locally without mocks. Confirm it fails deterministically in the current environment (it already does — see last three PRs).
- **GREEN** — implement the smallest fix (prefer fixture-timestamp injection over mocking `datetime`).
- **REFACTOR** — if the benchmark module exposes a time source, use it; otherwise leave the module alone and patch only at the test boundary.

---

## Handoff at end of session

Write `.superharness/handoffs/session-2026-04-16-post-v1.24.yaml` summarizing:

- What shipped: v1.21.0 → v1.24.1 with one-line descriptions.
- Current state: CI green, no open PRs, contract clean.
- Next sprint: Morpheme UI consumption of `resolved_model.label`, pointing to `artificemachine/morpheme` branch `feat/superharness-integration-morpheme` and the adapter-payload spec.
- Known unknown: whether v1.24.0's `cost_estimator` / `auto_dispatch` should also gain access to `resolved_model` (out of scope for v1.24, but worth a future look).
