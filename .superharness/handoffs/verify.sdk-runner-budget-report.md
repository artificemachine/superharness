# Handoff: verify.sdk-runner-budget

**Date**: 2026-03-30
**Task**: Verify SDKRunner budget enforcement and cost tracking (v1.3.0)
**Agent**: claude-code
**Status**: done

## Outcome

All 5 acceptance criteria verified via TDD. The SDKRunner implementation in
`src/superharness/engine/sdk_runner.py` was already correct. A comprehensive
dedicated test file was created to formally document and verify each criterion.

## Acceptance Criteria — Verified

1. **BudgetExceededError raised when cost exceeds max_budget_usd** — confirmed via
   4 tests in `TestBudgetEnforcement`. Error message contains "Budget exceeded" and
   the exception is raised after total_cost_usd > max_budget_usd across cumulative runs.

2. **run() returns dict with cost_usd, input_tokens, output_tokens** — confirmed via
   4 tests in `TestRunReturnShape`. All three keys are present and carry correct values.

3. **cost_usd calculated using MODEL_PRICING (same table as cost_estimator)** — confirmed
   via 3 tests in `TestCostCalculation`. Sonnet ($3/$15 per M), haiku ($0.25/$1.25 per M)
   pricing verified. `cost_estimator` imports `MODEL_PRICING` from `sdk_runner` directly,
   ensuring a single source of truth (`PRICING is MODEL_PRICING` assertion passes).

4. **Total cost accumulates across multiple run() calls** — confirmed via 3 tests in
   `TestCostAccumulation`. input_tokens, output_tokens, and total_cost_usd all sum
   correctly across sequential runs.

5. **reset_session() resets token and cost counters to zero** — confirmed via 4 tests in
   `TestResetSession`. All three counters (total_input_tokens, total_output_tokens,
   total_cost_usd) reset to 0; subsequent run() accumulates fresh from zero.

## Files Changed

- **Created**: `tests/unit/test_sdk_runner_budget.py` — 18 tests across 5 test classes,
  one per acceptance criterion. Uses `claude_agent_sdk` stub (no real SDK required).

- **No source changes** — `src/superharness/engine/sdk_runner.py` was already correctly
  implemented with `BudgetExceededError`, `_calculate_cost()`, `MODEL_PRICING`,
  accumulation logic in `run()`, and `reset_session()`.

- **Updated**: `.superharness/contract.yaml` — task status set to `done`, verified fields added.

- **Appended**: `.superharness/ledger.md` — outcome entry added.

## Test Results

```
tests/unit/test_sdk_runner_budget.py — 18 passed in 0.08s
tests/unit/test_sdk_runner.py — 16 passed (via SDK stub injected by budget test file)
Combined: 34 passed in 0.45s
```

Pre-existing failure in `tests/unit/test_delegate.py::test_delegate_claude_non_interactive_requires_specific_skip_permissions_confirmation` — confirmed pre-existing before this task (verified via git stash). Not a regression.

## TDD Summary

- **RED**: Tests written first. 3 of 18 tests failed due to lambda keyword arg mismatch in mock.
- **GREEN**: Lambda mocks fixed to use named `prompt` parameter. All 18 pass.
- **REFACTOR**: No source changes needed. Code quality confirmed.
