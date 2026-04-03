Task: Verify orchestrator --orchestrate flag, subtask routing, cost estimates (v1.3.0) (verify.orchestrator-subtask-routing-e2e)

## Acceptance Criteria
- delegate --orchestrate decomposes a task into subtasks and writes them to contract.yaml
- Each subtask has model_tier (mini/standard/max), estimated_tokens, estimated_cost_usd
- estimate_subtask_cost() returns correct USD for mini/standard/max tiers
- estimate_task_cost() sums subtask estimates with configurable buffer
- PRICING table in cost_estimator matches MODEL_PRICING in sdk_runner (single source of truth)
- Orchestrator falls back to single-subtask when Opus decomposition JSON is malformed

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done