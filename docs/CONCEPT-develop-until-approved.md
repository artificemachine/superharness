# CONCEPT — Pi-style `developIssuesUntilApproved` orchestration in superharness

Target repo: `~/DevOpsSec/superharness`
Source design doc: `docs/FLOW-pi-develop-issues-until-approved.md` (in superharness repo)

## 1. Scope summary

Build a deterministic in-process orchestration engine, `shux develop`, that takes a list of issues, runs a Developer-agent / Reviewer-agent loop per issue in an isolated git worktree (fresh agents every iteration, findings as the only carried memory, bounded by `max_iterations`), merges approved branches through a merge-agent loop, and emits a read-only summarizer report. Implementation reuses existing primitives: `SDKRunner` for agent invocation, `worktree_ops` for isolation, `handoffs_dao` for findings persistence, `issue_import` for GitHub issue ingestion.

NOT being built: watcher/inbox-based dispatch of lanes (this is an in-process loop like `swarm_dispatch`, not a queue workflow), task-lifecycle integration (no new task statuses, no `tasks` rows per lane), dashboard UI, CLI-harness agents (SDK path only, `claude-code` only), GitLab issue support beyond what `issue_import` already handles.

Smallest possible v1: single-issue `develop_until_approved` loop with mocked-agent tests and no CLI (Iterations 1-2).

## 2. Prerequisites

Dependencies:
- Python >= 3.11, existing superharness dev environment (`uv`), `pytest`.
- Claude Agent SDK availability for live runs (checked via `sdk_available()`, `src/superharness/engine/sdk_runner.py:178`). Tests mock `SDKRunner`; SDK not required for CI.
- `git` with worktree support (already required by `parallel_dispatch`).

Existing code areas touched:
- `src/superharness/engine/sdk_runner.py` — read-only reuse (`SDKRunner.run` returns `{output, input_tokens, output_tokens, cost_usd}`, raises `BudgetExceededError`).
- `src/superharness/engine/worktree_ops.py` — read-only reuse (`create_worktree`, `remove_worktree`, `sanitize_task_id`, `copy_superharness_state`).
- `src/superharness/engine/parallel_dispatch.py` — pattern reference (`fanout_dispatch`, `_try_merge`).
- `src/superharness/engine/swarm.py` — pattern reference (reviewer phase, `_parse_review_result`).
- `src/superharness/engine/handoffs_dao.py` — reuse `append` for findings persistence.
- `src/superharness/commands/issue_import.py` — reuse `_fetch_issue` / `_issue_to_task_fields`.
- `src/superharness/cli.py` — one new command registration (Iteration 6).

Risks:
- `SDKRunner` warm-start context cache could leak context between iterations; must pass `warm_start=False` for every lane agent (verified available at `sdk_runner.py:191`).
- Live watcher may be running on developer machines; the engine must never write to the inbox or task tables (fence below).
- Merge phase semantics: `_try_merge` merges into current HEAD of `project_dir`, not `main`; plan adopts the same semantics (merge into the branch the operator launched from) — documented, not silently changed.

Side-effect fence (all iterations): executor may touch the superharness repo tree and `tmp_path` fixtures only. Never write `~/.superharness` or any real project `.superharness/state.db`; never enqueue inbox rows; never spawn a real SDK/CLI agent in tests (always monkeypatch `SDKRunner`). Live SDK usage happens only in the manual demo in section 5, run by the operator.

## 3. Iterations

#### Iteration 1 — Verdict contract and prompt builders

**Goal:** Pure-function layer: `ReviewVerdict` dataclass, `parse_verdict()` (fail-closed), `build_developer_prompt()` and `build_reviewer_prompt()` in a new `engine/develop_loop.py`.

**Shippable on its own?** Yes — pure additive library module with tests, no callers required.

**Source references:**
- src/superharness/engine/swarm.py — `_parse_review_result` (line 86) and `_build_review_prompt` (line 46) are the closest existing parse/prompt pair; read before implementing to keep output-contract style consistent. Verify current signatures before reuse (referenced mechanisms rot).
- src/superharness/engine/schemas.py — existing pydantic conventions if a model is preferred over a dataclass.

**Files touched:**
- src/superharness/engine/develop_loop.py (new)
- tests/unit/engine/test_develop_verdict.py (new)

**Commit message:**
`feat(develop): add review verdict contract and prompt builders for develop loop`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/unit/engine/test_develop_verdict.py::test_parse_verdict_yaml_pass` — reviewer output containing `verdict: pass` with empty findings parses to `ReviewVerdict(passed=True, findings=[])`.
  - `tests/unit/engine/test_develop_verdict.py::test_parse_verdict_yaml_fail_with_findings` — `verdict: fail` plus a findings list yields `passed=False` and ordered findings strings.
  - `tests/unit/engine/test_develop_verdict.py::test_parse_verdict_garbage_fails_closed` — unparseable output returns `passed=False` with a synthetic finding `"unparseable reviewer output"`.
  - `tests/unit/engine/test_develop_verdict.py::test_developer_prompt_includes_prior_findings` — findings from iteration N appear verbatim in the iteration N+1 developer prompt.
  - `tests/unit/engine/test_develop_verdict.py::test_reviewer_prompt_demands_structured_verdict` — reviewer prompt contains the exact literal `verdict:` contract block and instructs findings as a YAML list.
- GREEN (minimal implementation to pass RED):
  - `@dataclass ReviewVerdict(passed: bool, findings: list[str], raw: str)`.
  - `parse_verdict(output: str) -> ReviewVerdict`: extract fenced or bare YAML block containing `verdict:`; fallback regex `^verdict:\s*(pass|fail)`; anything else fails closed.
  - `build_developer_prompt(issue: dict, findings: list[str], iteration: int) -> str`; `build_reviewer_prompt(issue: dict, iteration: int) -> str` (reviewer prompt instructs reading the worktree diff and returning the verdict block).
- REFACTOR (cleanup planned after GREEN):
  - Extract shared YAML-block extraction helper if parse grows past ~30 lines. Otherwise none.

**Test pyramid for this iteration:**
- Smoke: `import superharness.engine.develop_loop` succeeds (implicit in test collection; add `test_module_imports`).
- Unit: 5 tests listed above, all in `tests/unit/engine/test_develop_verdict.py`.
- Integration: N/A — pure functions.
- State machine: N/A — no FSM touched.
- Contract: `test_reviewer_prompt_demands_structured_verdict` doubles as the output-contract check (the literal verdict block is the contract).
- Regression: none — pure addition; nothing existing can break.
- Chaos: `test_parse_verdict_garbage_fails_closed` is the bad-input case.
- E2E: N/A.
- Performance: N/A.
- TDD Parity: 100% — all 4 public symbols (`ReviewVerdict`, `parse_verdict`, `build_developer_prompt`, `build_reviewer_prompt`) directly tested.
- Coverage: +1% → 57% (small module, fully covered; `fail_under = 56` in pyproject.toml line 79 unchanged).

**Acceptance criteria (binary):**
- [ ] `parse_verdict` returns `passed=False` for empty string, prose-only output, and malformed YAML.
- [ ] All 5 RED tests pass; no other test file modified.

**Estimated effort:** S

**Blocked by:** None

#### Iteration 2 — `develop_until_approved` single-lane loop

**Goal:** The bounded Developer→Reviewer iteration loop for one issue in a given working directory, fresh `SDKRunner` per agent per iteration, findings persisted via `handoffs_dao`, returning a `LaneResult`.

**Shippable on its own?** Yes — callable engine API with full mocked-agent test coverage; CLI comes later.

**Source references:**
- src/superharness/engine/sdk_runner.py — `SDKRunner.__init__` (line 191: `project_dir, model, max_budget_usd, warm_start`) and `.run` (line 211, returns dict with `output`/`cost_usd`, raises `BudgetExceededError` line 117). Verify signature before coding; loop must construct with `warm_start=False`.
- src/superharness/engine/handoffs_dao.py — `append(conn, *, task_id, phase, status, from_agent, to_agent, content, metadata, now)` (line 22). Verify keyword names before use.
- src/superharness/engine/db.py — how callers obtain `conn` for the DAO (follow an existing `handoffs_dao.append` call site).

**Files touched:**
- src/superharness/engine/develop_loop.py (modified)
- tests/unit/engine/test_develop_loop.py (new)

**Commit message:**
`feat(develop): add develop_until_approved bounded developer/reviewer loop`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/unit/engine/test_develop_loop.py::test_pass_first_iteration_returns_approved` — mocked reviewer passes on iteration 1; `LaneResult.approved is True`, `iterations == 1`.
  - `tests/unit/engine/test_develop_loop.py::test_findings_carried_into_next_developer_prompt` — reviewer fails iteration 1 with findings; developer prompt of iteration 2 contains those findings.
  - `tests/unit/engine/test_develop_loop.py::test_gives_up_after_max_iterations` — reviewer always fails; loop stops at `max_iterations`, `approved is False`, `failure_reason == "review_failed"`.
  - `tests/unit/engine/test_develop_loop.py::test_fresh_runner_per_agent_per_iteration` — with M=2 full iterations, `SDKRunner` constructed exactly 4 times, every call with `warm_start=False`.
  - `tests/unit/engine/test_develop_loop.py::test_handoff_rows_written_per_iteration` — each iteration appends one developer handoff and one reviewer handoff (phase strings `develop:iter-<n>:dev` / `develop:iter-<n>:review`).
  - `tests/unit/engine/test_develop_loop.py::test_budget_exceeded_marks_lane_failed` — `SDKRunner.run` raising `BudgetExceededError` yields `approved is False`, `failure_reason == "budget_exceeded"`, no crash.
- GREEN (minimal implementation to pass RED):
  - `@dataclass LaneResult(issue_id: str, approved: bool, iterations: int, findings_history: list[list[str]], cost_usd: float, failure_reason: str = "", branch: str = "")`.
  - `develop_until_approved(project_dir: str, issue: dict, max_iterations: int = 3, developer_model: str | None = None, reviewer_model: str | None = None, max_budget_per_agent: float | None = None, runner_factory=SDKRunner) -> LaneResult` — `runner_factory` injected for tests (explicit dependency injection per house style).
  - Loop: build dev prompt → run dev runner → build review prompt → run review runner → `parse_verdict` → pass: return; fail: record findings, next iteration.
- REFACTOR (cleanup planned after GREEN):
  - Extract `_run_agent(factory, project_dir, model, budget, prompt) -> tuple[str, float]` helper shared by both roles.

**Test pyramid for this iteration:**
- Smoke: `test_pass_first_iteration_returns_approved` (loop wires end-to-end with mocks).
- Unit: 6 tests above; `SDKRunner` monkeypatched with a recording fake.
- Integration: handoff persistence test uses a real temp SQLite via existing `clean_harness` conftest fixture (tests/conftest.py line 149) — this is the DB boundary exercised.
- State machine: N/A — task FSM untouched by design.
- Contract: N/A — covered in Iteration 1.
- Regression: none — pure addition; assert no writes to `tasks` or `inbox` tables in `test_handoff_rows_written_per_iteration` (guards the fence).
- Chaos: `test_budget_exceeded_marks_lane_failed` (failure injection via raising fake).
- E2E: N/A.
- Performance: N/A.
- TDD Parity: 100% — both new public symbols (`LaneResult`, `develop_until_approved`) directly tested.
- Coverage: +1% → 58%.

**Acceptance criteria (binary):**
- [ ] With an always-fail fake reviewer and M=3, exactly 6 `SDKRunner` constructions occur and the loop terminates.
- [ ] No rows appear in `tasks` or `inbox` tables after a full loop run against the `clean_harness` fixture.

**Estimated effort:** M

**Blocked by:** Iteration 1

#### Iteration 3 — Parallel issue fan-out with worktree isolation

**Goal:** `develop_issues()` in new `engine/develop_issues.py`: one worktree + branch `develop/<safe-issue-id>` per issue, one thread per lane running `develop_until_approved`, failed-lane worktrees removed, approved branches kept for merge.

**Shippable on its own?** Yes — returns `list[LaneResult]`; merge phase not yet required for the API to be useful (operator can merge approved branches by hand).

**Source references:**
- src/superharness/engine/parallel_dispatch.py — `fanout_dispatch` (line 147) is the thread/worktree template: worktree creation loop (lines 176-193), thread join (line 210), cleanup in `finally` (lines 217-220). Read before implementing; copy the pattern, not the code.
- src/superharness/engine/worktree_ops.py — `sanitize_task_id` (line 10), `WorktreeSlot` (line 22), `create_worktree` (line 36), `remove_worktree` (line 48), `copy_superharness_state` (line 60). Verify signatures at implementation time.

**Files touched:**
- src/superharness/engine/develop_issues.py (new)
- tests/unit/engine/test_develop_issues.py (new)

**Commit message:**
`feat(develop): parallel per-issue fan-out with isolated worktrees`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/unit/engine/test_develop_issues.py::test_worktree_and_branch_per_issue` — 2 issues in a temp git repo produce worktrees on branches `develop/issue-65` and `develop/issue-66` while lanes run (loop body mocked).
  - `tests/unit/engine/test_develop_issues.py::test_results_one_per_issue_in_input_order` — returned list length equals input length, `issue_id` order preserved.
  - `tests/unit/engine/test_develop_issues.py::test_failed_lane_worktree_removed_approved_branch_kept` — mocked one approved + one failed lane: failed worktree and branch gone; approved branch still exists (worktree may be removed, branch must survive).
  - `tests/unit/engine/test_develop_issues.py::test_lane_exception_isolated` — one lane raising does not prevent other lanes finishing; raising lane yields `approved is False`, `failure_reason == "lane_error"`.
  - `tests/unit/engine/test_develop_issues.py::test_worktree_create_failure_fails_lane_only` — `create_worktree` returning False for one issue fails that lane, others proceed.
  - `tests/unit/engine/test_develop_issues.py::test_empty_issue_list_returns_empty` — no worktrees created, empty result.
- GREEN (minimal implementation to pass RED):
  - `develop_issues(project_dir: str, issues: list[dict], max_iterations: int = 3, **lane_kwargs) -> list[LaneResult]`.
  - Per issue: `sanitize_task_id` → branch `develop/<safe>` → `create_worktree` under `<project>/.superharness/worktrees/` (same base as `parallel_dispatch.py` line 170) → `copy_superharness_state` → `threading.Thread(target=lane)` where lane runs `develop_until_approved` with `project_dir=worktree_path`, wrapped in try/except storing `failure_reason="lane_error"`.
  - Join all; remove worktrees of non-approved lanes (worktree and branch); approved lanes: remove worktree, keep branch, stamp `LaneResult.branch`.
- REFACTOR (cleanup planned after GREEN):
  - Extract `_setup_lane(project_dir, issue) -> WorktreeSlot | None` and `_teardown_lane(project_dir, slot, approved)`.

**Test pyramid for this iteration:**
- Smoke: `test_empty_issue_list_returns_empty`.
- Unit: 6 tests above; `develop_until_approved` monkeypatched, real `git` in `tmp_path` repos (init + one commit fixture helper).
- Integration: worktree tests hit real git — that is the boundary exercised (no mocked subprocess).
- State machine: N/A.
- Contract: N/A.
- Regression: `fanout_dispatch` untouched — assert by not modifying `parallel_dispatch.py` (pure addition).
- Chaos: `test_worktree_create_failure_fails_lane_only`, `test_lane_exception_isolated`.
- E2E: N/A.
- Performance: N/A (thread count = issue count; cap deferred, see Out of scope).
- TDD Parity: 100% — `develop_issues` plus both helpers exercised via the 6 tests.
- Coverage: +1% → 59%.

**Acceptance criteria (binary):**
- [ ] After a run with one approved and one failed mocked lane: `git branch --list 'develop/*'` shows exactly the approved branch; `git worktree list` shows only the main tree.
- [ ] All 6 RED tests pass on a clean checkout.

**Estimated effort:** M

**Blocked by:** Iteration 2

#### Iteration 4 — Merge phase (merge-agent loop on the launch branch)

**Goal:** `merge_approved()` in `engine/develop_issues.py`: fast-path plain `git merge` of each approved branch into the branch the run started from; on conflict or post-merge test failure, a Merge-Developer/Merge-Reviewer agent loop bounded by `max_iterations`; skip entirely when nothing approved.

**Shippable on its own?** Yes — completes the branch-to-mainline path; `develop_issues` callers can now get merged output.

**Source references:**
- src/superharness/engine/parallel_dispatch.py — `_try_merge` (line 125): `git merge --no-commit --no-ff`, commit on success, `git merge --abort` on failure, merges into current HEAD. Read and verify behavior before building on it — the plan reuses its semantics (merge into current HEAD, never force-switch to main). If its implementation has drifted from this description, adapt the new code, not `_try_merge`.
- src/superharness/engine/swarm.py — auto-merge path (winner staging + merge, lines 196-266) shows the stage/commit-inside-worktree steps a merge must not forget; read before implementing.

Reuse note (executor: read before coding): `develop_until_approved`, created in Iteration 2 inside `engine/develop_loop.py`, is reused verbatim for the merge loop with a merge-scoped issue dict (`{"title": "merge approved develop branches", "context": <branch list>}`). Verify its as-landed signature before use.

**Files touched:**
- src/superharness/engine/develop_issues.py (modified)
- tests/unit/engine/test_develop_merge.py (new)

**Commit message:**
`feat(develop): merge phase with agent-assisted conflict resolution loop`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/unit/engine/test_develop_merge.py::test_skip_when_none_approved` — empty approved list returns `MergeResult(skipped=True)`; zero subprocess and zero agent calls.
  - `tests/unit/engine/test_develop_merge.py::test_clean_merge_uses_no_agents` — two non-conflicting branches in a temp repo merge; `SDKRunner` factory never called; both branch tips reachable from HEAD.
  - `tests/unit/engine/test_develop_merge.py::test_conflict_triggers_agent_loop` — two branches editing the same line: fast path aborts, mocked merge loop invoked once with the conflicting branch names in its issue context.
  - `tests/unit/engine/test_develop_merge.py::test_agent_loop_failure_reports_unmerged` — mocked merge loop returns `approved=False`; `MergeResult.merged_branches` excludes the conflicted branch, `failed_branches` includes it, repo left on original branch with clean status.
  - `tests/unit/engine/test_develop_merge.py::test_abort_leaves_tree_clean` — after a failed fast-path merge, `git status --porcelain` is empty and HEAD equals pre-merge HEAD.
  - `tests/unit/engine/test_develop_merge.py::test_refuses_to_merge_onto_main` — with `main` checked out in the fixture repo, `merge_approved` returns `MergeResult(skipped=True)` whose reason names the never-merge-to-main doctrine; zero agents spawned, zero branches merged. Same assertion for `master`.
- GREEN (minimal implementation to pass RED):
  - `@dataclass MergeResult(skipped: bool, merged_branches: list[str], failed_branches: list[str], iterations: int, cost_usd: float)`.
  - `merge_approved(project_dir: str, results: list[LaneResult], max_iterations: int = 3, **agent_kwargs) -> MergeResult`.
  - For each approved branch: try plain merge (mirror `_try_merge` semantics locally, own implementation); on failure abort, collect branch into conflict set. If conflict set non-empty: run `develop_until_approved` once over a synthetic merge issue listing conflicted branches (the merge Developer agent runs in `project_dir` itself, no worktree — matches Pi diagram "developUntilApproved on main").
  - Delete merged branches after success.
- REFACTOR (cleanup planned after GREEN):
  - Extract `_plain_merge(project_dir, branch) -> bool`.

**Test pyramid for this iteration:**
- Smoke: `test_skip_when_none_approved`.
- Unit: 5 tests above.
- Integration: real-git merge/conflict scenarios in `tmp_path` repos (subprocess boundary exercised for real).
- State machine: N/A.
- Contract: N/A.
- Regression: `test_abort_leaves_tree_clean` guards the known `_try_merge` footgun (dirty tree / detached state after failed merge).
- Chaos: conflict injection is the chaos case (`test_conflict_triggers_agent_loop`).
- E2E: N/A.
- Performance: N/A.
- TDD Parity: 100% — `MergeResult`, `merge_approved`, `_plain_merge` all covered.
- Coverage: +1% → 60%.

**Acceptance criteria (binary):**
- [ ] Clean-merge path completes with zero `SDKRunner` constructions.
- [ ] After any failed merge path, `git status --porcelain` in the fixture repo is empty and the original branch is checked out.
- [ ] With `main` or `master` checked out, `merge_approved` skips with a doctrine reason and spawns zero agents.

**Estimated effort:** M

**Blocked by:** Iteration 3

#### Iteration 5 — Summarizer and result assembly

**Goal:** Read-only Summarizer agent (exactly one, prompt forbids file changes) plus `run_develop_workflow()` assembling the Pi output shape `{issues, issueResults, merge, summary}`.

**Shippable on its own?** Yes — the engine API is complete; CLI is the only remaining surface.

**Source references:**
- src/superharness/engine/sdk_runner.py — same runner reuse; verify `run()` return keys (`output`, `input_tokens`, `output_tokens`, `cost_usd`, lines 297-302).

Reuse note (executor: read before coding): Iteration 3/4 results (`LaneResult`, `MergeResult` in `engine/develop_issues.py`, created earlier in this plan) feed the assembler. Verify field names as landed, not as planned.

**Files touched:**
- src/superharness/engine/develop_issues.py (modified)
- tests/unit/engine/test_develop_summary.py (new)

**Commit message:**
`feat(develop): summarizer agent and workflow result assembly`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/unit/engine/test_develop_summary.py::test_summary_prompt_is_read_only` — summarizer prompt contains explicit "do not modify files" clause and receives serialized lane + merge results.
  - `tests/unit/engine/test_develop_summary.py::test_output_shape` — `run_develop_workflow` returns dict with exactly keys `issues`, `issueResults`, `merge`, `summary`.
  - `tests/unit/engine/test_develop_summary.py::test_summary_failure_degrades_gracefully` — summarizer raising yields `summary` containing `"summarizer_failed"` marker, workflow still returns.
  - `tests/unit/engine/test_develop_summary.py::test_workflow_orchestration_order` — recording fakes prove order: fan-out → merge → summary, and merge skipped when no lane approved.
- GREEN (minimal implementation to pass RED):
  - `summarize(project_dir, results, merge_result, runner_factory=SDKRunner, model=None, max_budget=None) -> str`.
  - `run_develop_workflow(project_dir, issues, max_iterations=3, **kwargs) -> dict` calling `develop_issues` → `merge_approved` (skip-aware) → `summarize`, try/except around summarize only.
- REFACTOR (cleanup planned after GREEN):
  - None expected.

**Test pyramid for this iteration:**
- Smoke: `test_output_shape`.
- Unit: 4 tests above.
- Integration: N/A — components integration-tested in Iteration 6 pipeline test.
- State machine: N/A.
- Contract: `test_output_shape` is the output-contract check (Pi-compatible shape).
- Regression: `test_workflow_orchestration_order` guards skip-merge branch (the Pi "if none approved" bypass).
- Chaos: `test_summary_failure_degrades_gracefully`.
- E2E: N/A.
- Performance: N/A.
- TDD Parity: 100% — `summarize`, `run_develop_workflow` covered.
- Coverage: +1% → 61%.

**Acceptance criteria (binary):**
- [ ] With zero approved lanes, `merge["skipped"] is True` and summarizer still runs.
- [ ] Summarizer exception does not propagate out of `run_develop_workflow`.

**Estimated effort:** S

**Blocked by:** Iteration 4

#### Iteration 6 — CLI `shux develop` with policy and budget gate

**Goal:** New `commands/develop_cmd.py` click command registered in `cli.py`: `shux develop --issues <ids-or-urls> [--max-iter N] [--model M] [--budget-per-agent X] [--dry-run] [--json] [--yes]`; refuses without `profile.autonomy == "ai_driven"` unless `--yes`; GitHub URLs resolved via `issue_import`; plus the end-to-end pipeline integration test.

**Shippable on its own?** Yes — closes the user-facing path.

**Source references:**
- src/superharness/cli.py — command registration convention; find an existing `@main.command()`/group registration (e.g. the delegate wiring near line 377) and mirror it. Verify the exact registration pattern in the current file before adding.
- src/superharness/commands/issue_import.py — `_fetch_issue` (line 29) and `_issue_to_task_fields` (line 57); verify signatures. Plain numeric IDs are used as issue dicts `{"id": "<n>", "title": "issue <n>"}` without network; URLs go through `_fetch_issue`.
- src/superharness/commands/workflow_cmd.py — profile read pattern and `_effective` shape (line 62) for the autonomy gate.
- src/superharness/engine/cost_estimator.py — read to decide whether a pre-run cost preview line can be reused in `--dry-run`; if its API does not fit in 5 lines of glue, print the agent-count formula (2NM + 2M + 1) instead.

**Files touched:**
- src/superharness/commands/develop_cmd.py (new)
- src/superharness/cli.py (modified)
- tests/unit/test_develop_cmd.py (new)
- tests/integration/test_develop_pipeline.py (new)
- CHANGELOG.md (modified — append entry; required by repo policy on every commit, all iterations)

**Commit message:**
`feat(develop): shux develop CLI with autonomy gate and budget caps`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/unit/test_develop_cmd.py::test_dry_run_spawns_no_agents` — `--dry-run` prints issue list, max iterations, worst-case agent count `2NM + 2M + 1`, and exits 0 with `run_develop_workflow` never called.
  - `tests/unit/test_develop_cmd.py::test_refuses_without_autonomy_or_yes` — profile without `autonomy: ai_driven` and no `--yes` exits non-zero with a message naming both unlock paths.
  - `tests/unit/test_develop_cmd.py::test_yes_flag_overrides_autonomy_gate` — same profile, `--yes` proceeds (workflow mocked).
  - `tests/unit/test_develop_cmd.py::test_budget_flag_threaded_to_workflow` — `--budget-per-agent 0.50` reaches `run_develop_workflow` kwargs.
  - `tests/unit/test_develop_cmd.py::test_github_url_resolved_via_issue_import` — URL argument triggers mocked `_fetch_issue`; numeric ID does not.
  - `tests/unit/test_develop_cmd.py::test_json_output_shape` — `--json` emits parseable JSON with the four output keys.
  - `tests/integration/test_develop_pipeline.py::test_full_pipeline_two_issues_mocked_sdk` — `clean_harness`-style temp git project, fake `SDKRunner` scripted so issue A passes on iteration 1 and issue B fails M times: final JSON shows one merged branch, one failed lane, summary present; no `tasks`/`inbox` rows written; no worktrees left behind.
- GREEN (minimal implementation to pass RED):
  - Click command parsing `--issues` (comma-separated), gate check reading `profile.yaml` (same loader as `workflow_cmd`), default `--budget-per-agent` from `profile.budget.develop_per_agent_usd` else 1.00, call `run_develop_workflow`, render text or JSON.
  - Registration line in `cli.py` following existing convention.
- REFACTOR (cleanup planned after GREEN):
  - Extract `_parse_issue_args(raw: str) -> list[dict]` helper.

**Test pyramid for this iteration:**
- Smoke: `test_dry_run_spawns_no_agents` (CLI wired, imports resolve, exit 0).
- Unit: 6 CLI tests via `click.testing.CliRunner`.
- Integration: `test_full_pipeline_two_issues_mocked_sdk` — real git worktrees + real SQLite handoffs + fake SDK.
- State machine: N/A — verified by fence assertion (no task rows) rather than transitions.
- Contract: `test_json_output_shape` (CLI output contract).
- Regression: pipeline test asserts no leftover worktrees (guards Iteration 3 cleanup under composed use).
- Chaos: covered inside pipeline test via the always-fail lane.
- E2E: `test_full_pipeline_two_issues_mocked_sdk` is the E2E (full user path minus live SDK, which the fence forbids in tests).
- Performance: N/A — run time dominated by mocked agents.
- TDD Parity: 100% — command entry + `_parse_issue_args` covered.
- Coverage: +1% → 62%; `fail_under = 56` (pyproject.toml line 79) stays — do not raise in this plan.

**Acceptance criteria (binary):**
- [ ] `shux develop --issues 65 --dry-run` exits 0 on a repo with no SDK installed.
- [ ] Gate refusal message printed and exit code non-zero when autonomy is unset and `--yes` absent.
- [ ] Pipeline test leaves `git worktree list` with only the main tree.

**Estimated effort:** M

**Blocked by:** Iteration 5

## 4. Test inventory summary

| Iter | Smoke | Unit | Integration | State machine | Contract | Regression | Chaos | E2E | Performance | TDD Parity | Coverage Δ |
|------|-------|------|-------------|---------------|----------|------------|-------|-----|-------------|------------|------------|
| 1    | 1     | 5    | 0           | 0             | 1        | 0          | 1     | 0   | 0           | 100%       | +1% → 57%  |
| 2    | 1     | 6    | 1           | 0             | 0        | 1          | 1     | 0   | 0           | 100%       | +1% → 58%  |
| 3    | 1     | 6    | (real git)  | 0             | 0        | 0          | 2     | 0   | 0           | 100%       | +1% → 59%  |
| 4    | 1     | 6    | (real git)  | 0             | 1        | 1          | 1     | 0   | 0           | 100%       | +1% → 60%  |
| 5    | 1     | 4    | 0           | 0             | 1        | 1          | 1     | 0   | 0           | 100%       | +1% → 61%  |
| 6    | 1     | 6    | 1           | 0             | 1        | 1          | 1     | 1   | 0           | 100%       | +1% → 62%  |

## 5. End-to-end definition of done

Deduplicated acceptance criteria:
- Verdict parsing fails closed on any malformed reviewer output.
- Fresh `SDKRunner` (with `warm_start=False`) per agent per iteration; exactly 2 constructions per iteration per lane.
- Loop bounded by `max_iterations`; findings are the only state carried between iterations; each iteration persists two handoff rows.
- One worktree/branch per issue; failed lanes fully cleaned; approved branches survive until merged; no worktrees left after a full run.
- Merge skipped when zero approvals; clean merges use zero agents; failed merges leave a clean tree on the original branch.
- Output dict has exactly `issues`, `issueResults`, `merge`, `summary`; summarizer failure never breaks the workflow.
- CLI gates on `autonomy == "ai_driven"` or `--yes`; `--dry-run` spawns nothing; per-agent budget always set.
- No writes to `tasks` or `inbox` tables anywhere in the workflow.

Manual demo (operator-run, live SDK, the only live-agent step):
```bash
cd ~/DevOpsSec/superharness && shux develop --issues 65 --max-iter 2 --budget-per-agent 0.50 --yes --json
```
Expect: JSON with `issueResults[0].approved`, a merged or surviving `develop/issue-65` branch, summary text.

Green command at the end:
```bash
cd ~/DevOpsSec/superharness && uv run pytest tests/unit/engine/test_develop_verdict.py tests/unit/engine/test_develop_loop.py tests/unit/engine/test_develop_issues.py tests/unit/engine/test_develop_merge.py tests/unit/engine/test_develop_summary.py tests/unit/test_develop_cmd.py tests/integration/test_develop_pipeline.py -q
```

## 6. Out of scope

- Watcher/inbox-dispatched lanes (CLI-harness agents, codex/gemini as developers) — different execution substrate; revisit once SDK path proves the loop.
- Task-lifecycle integration (one `tasks` row per lane with review statuses, dashboard visibility) — valuable but doubles surface area; needs a design pass on status mapping first.
- Concurrency cap on lane threads — issue counts are small today; add when someone passes 20 issues.
- Reviewer diversity (multiple reviewers voting per iteration) — single reviewer matches Pi v1.
- GitLab issue URLs beyond `issue_import`'s existing behavior — inherits whatever it does, no new work.
- Raising `fail_under` above 56 — do after coverage gains are measured, not predicted.
- Auto-closing the source GitHub issue after merge — `close.py` prints manual commands today; keep parity.

## 7. Open questions

Both resolved 2026-07-31. None outstanding.

**Merge-phase base branch — resolved: merge into the branch the run was launched from, never `main`.** This matches `_try_merge`'s existing semantics (`parallel_dispatch.py:125` merges into current HEAD), and more importantly the alternative is forbidden: repo doctrine is never to merge or commit directly to `main`, always via PR. A tool that force-merges agent branches into `main` would violate that on every run. `merge_approved` must therefore refuse to run when HEAD is `main` or `master`, and Iteration 4 gains one acceptance criterion: with `main` checked out, `merge_approved` returns `MergeResult(skipped=True)` with a reason naming the doctrine, and spawns zero agents.

**Default `max_iterations` — resolved: 3, not Pi's 5.** Rationale: a Pi iteration is a full Developer plus Reviewer cycle, far more expensive than the cheap re-dispatch that `max_retries=3` governs at enqueue, so the repo's existing 3 is the better anchor. Worst-case agent count drops from `2NM + 2M + 1` = 41 at N=3, M=5 to 25 at M=3, a 39% cut in the ceiling, and a reviewer that has rejected three successive attempts rarely converges on the fourth. The `--max-iter` flag keeps 5 one argument away when a specific issue warrants it. All signatures in this plan now default to 3.
