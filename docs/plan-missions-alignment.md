# Missions Alignment Plan

Source: Luke Alvoeiro, Factory — "The Multi-Agent Architecture That Actually Ships"
Video: https://youtu.be/ow1we5PzK-o

## Context

Factory's "Missions" solves the same problem as superharness: long-running multi-agent
coordination with structured handoffs. The architectures converge on the same primitives
(orchestrator / workers / validators, structured handoffs, shared state, serial execution).
The gaps below are where Factory is ahead and where superharness can improve.

---

## Alignment Map

| Factory concept | superharness equivalent | Status |
|---|---|---|
| Orchestrator / Worker / Validator roles | task owner / agent dispatch / review cycle | aligned |
| Structured handoffs (outcome, commands, exit codes, issues) | handoff YAML with `outcome`, `context`, `tests_passed` | aligned |
| Serial feature execution | one task `in_progress` at a time | aligned |
| Shared state as source of truth | SQLite `state.db` | aligned |
| Broadcast through shared mission state | `shux contract` / dashboard | aligned |
| Self-heal at milestone boundaries | `review_failed` loops to `plan_proposed` | aligned |
| Mission control dashboard | dashboard at port 8787 | aligned |

---

## Gaps

### Gap 1 — Validation contracts written pre-code (HIGH)

Factory locks the validation contract during planning, before any implementation agent
runs. It defines "done" independently of the code that will be written. Superharness has
TDD blocks but they are authored by the implementing agent — creating a sunk-cost bias
toward the implementation approach.

**Effect:** tests written after code confirm decisions rather than catching bugs.
The validator checks the same mental model the worker had.

### Gap 2 — Fresh-context validators (HIGH)

Factory validators have never seen the worker's code or context. Adversarial by design.
Superharness review agents can inherit state from the same session context as the worker.

**Effect:** the reviewer is anchored on the implementer's framing, reducing defect
detection rate.

### Gap 3 — Model routing per role (MEDIUM)

Factory routes models deliberately: orchestrator = slow + deep reasoning, worker = fast +
code fluency, validator = precise instruction following. `shux delegate` uses a flat model
config with no role differentiation.

**Effect:** wrong model in the wrong seat compounds over a 3-day run. A validator using a
creative model produces inconsistent verdicts.

### Gap 4 — Parallel read-only operations within a task (MEDIUM)

Factory parallelizes read-only subagents (code search, API research, code review) inside
a feature while keeping feature execution serial. Superharness is fully serial at every
level.

**Effect:** validator wall-clock time is unnecessarily long; code review agents for
multiple features must wait in sequence.

### Gap 5 — Behavioral / user-testing validator (LOW — experimental)

Factory spawns the application and drives it via computer use to verify end-to-end flows.
`shux verify` is a human gate, not an agent-driven behavioral check.

**Effect:** functional regressions in long-running missions are only caught by a human
reviewing a report, not automatically at milestone boundaries.

---

## Implementation Plan

Each iteration follows Red → Green → Refactor.
Unit tests cover the new logic in isolation.
E2E tests cover the full task lifecycle change.

---

### Iter 1 — Pre-code validation contracts

**What:** lock the acceptance criteria and TDD contract at `plan_approved` as an
immutable artifact. Surface it verbatim (no paraphrase, no reinterpretation) to the
review agent at `review_requested`. The reviewer grades against the locked contract,
not against the code it sees.

**Why:** decouples "what done means" from "how it was implemented". Prevents the
validator from inheriting the worker's bias.

#### Red (failing tests first)

```python
# tests/unit/test_contract_lock.py

def test_contract_locked_at_plan_approved(db):
    """Contract fields are frozen and cannot be modified after plan_approved."""
    task = create_task(db, status="plan_proposed", acceptance_criteria="original")
    approve_plan(db, task.id)
    with pytest.raises(ContractLockError):
        update_acceptance_criteria(db, task.id, "modified")

def test_contract_surfaced_to_reviewer_verbatim(db):
    """Handoff generated at review_requested includes the locked contract verbatim."""
    task = create_task(db, status="in_progress", acceptance_criteria="must do X")
    advance_to_review(db, task.id)
    handoff = generate_review_handoff(db, task.id)
    assert "must do X" in handoff["validation_contract"]
    assert handoff["validation_contract"] == task.locked_contract
```

#### Green

- Add `locked_contract` column to `tasks` table (TEXT, nullable).
- On `plan_approved` transition: snapshot `acceptance_criteria` + `tdd` block into
  `locked_contract`, set `contract_locked_at` timestamp.
- Block writes to `acceptance_criteria` and `tdd` fields when `contract_locked_at`
  is set. Raise `ContractLockError`.
- Extend `generate_review_handoff()` to include `validation_contract` key from
  `locked_contract`.

#### Refactor

- Extract `ContractLocker` class so the snapshot + lock logic is testable independently
  of the transition handler.
- Add `shux context <id>` output section: `Locked Contract (immutable)`.

#### E2E test

```python
# tests/integration/test_contract_lock_lifecycle.py

def test_full_lifecycle_contract_surfaced_at_review(tmp_project):
    """End-to-end: contract locked at plan_approved appears in review handoff."""
    tid = shux("task create --title 'auth' --criteria 'login must reject bad tokens'")
    shux(f"task status {tid} plan_proposed")
    shux(f"task status {tid} plan_approved")
    # Attempt to modify — must be blocked
    result = shux(f"task update {tid} --criteria 'anything'", check=False)
    assert result.returncode != 0
    shux(f"task status {tid} in_progress")
    shux(f"task status {tid} report_ready")
    shux(f"task status {tid} review_requested")
    handoff = shux_json(f"handoff-generate {tid}")
    assert "login must reject bad tokens" in handoff["validation_contract"]
```

---

### Iter 2 — Fresh-context validator dispatch

**What:** when `review_requested` triggers agent dispatch, spawn the review agent in
a clean worktree with no inherited session state from the worker. Pass only: the locked
contract, the diff since `plan_approved`, and the handoff report.

**Why:** validators anchored on the implementer's framing miss the same bugs the
implementer missed. Fresh context is the whole point of a separate validator role.

#### Red

```python
# tests/unit/test_fresh_context_dispatch.py

def test_review_dispatch_uses_clean_worktree(db, mocker):
    """Review agent dispatch creates a new worktree, not the same as worker."""
    task = advance_to_review(db)
    dispatch = capture_dispatch_args(db, task.id, role="validator")
    assert dispatch["worktree"] != task["worker_worktree"]
    assert dispatch["inherited_context"] == []

def test_review_dispatch_payload_contains_only_contract_and_diff(db):
    """Review agent receives locked contract + diff only — no worker session log."""
    task = advance_to_review(db)
    payload = build_review_payload(db, task.id)
    assert "locked_contract" in payload
    assert "diff_since_plan_approved" in payload
    assert "worker_session_log" not in payload
    assert "worker_context_window" not in payload
```

#### Green

- Extend `shux delegate` to accept `--role validator`.
- `--role validator` forces: new worktree (even if main is clean), payload limited to
  `locked_contract` + `diff_since_plan_approved` + `handoff_report`.
- Store `worker_worktree` on the task at `in_progress` dispatch time so the validator
  gets a different one.

#### Refactor

- Introduce `DispatchProfile` dataclass: `{role, worktree_policy, payload_filter}`.
  Three profiles: `orchestrator`, `worker`, `validator`.
- Move payload-building logic into `DispatchProfile.build_payload()`.

#### E2E test

```python
# tests/integration/test_fresh_validator_dispatch.py

def test_validator_worktree_is_isolated_from_worker(tmp_project):
    tid = run_task_to_report_ready(tmp_project)
    shux(f"task status {tid} review_requested")
    dispatch_log = shux_json(f"delegate {tid} --role validator --dry-run")
    worker_wt = shux_json(f"context {tid}")["worker_worktree"]
    assert dispatch_log["worktree"] != worker_wt
    assert "worker_session_log" not in dispatch_log["payload"]
```

---

### Iter 3 — Model routing per role

**What:** add `--role orchestrator|worker|validator` flag to `shux delegate`. Each role
maps to a configurable model preset in `shux workflow`. Default presets:

| Role | Default model |
|---|---|
| orchestrator | `claude-opus-4-6` (slow, deep reasoning) |
| worker | `claude-sonnet-4-6` (fast, code fluency) |
| validator | `claude-sonnet-4-6` (precise instruction following) |

**Why:** wrong model in the wrong seat compounds over multi-day runs. Validator with a
creative model produces inconsistent verdicts.

#### Red

```python
# tests/unit/test_model_routing.py

def test_role_maps_to_model_preset(workflow_config):
    router = ModelRouter(workflow_config)
    assert router.model_for("orchestrator") == "claude-opus-4-6"
    assert router.model_for("worker") == "claude-sonnet-4-6"
    assert router.model_for("validator") == "claude-sonnet-4-6"

def test_custom_preset_overrides_default(workflow_config):
    workflow_config["model_routing"]["validator"] = "claude-haiku-4-5-20251001"
    router = ModelRouter(workflow_config)
    assert router.model_for("validator") == "claude-haiku-4-5-20251001"

def test_delegate_passes_model_to_dispatch(db, mocker):
    dispatch = capture_dispatch_args(db, task_id, role="validator")
    assert dispatch["model"] == "claude-sonnet-4-6"
```

#### Green

- Add `model_routing` section to `shux workflow` schema:
  ```yaml
  model_routing:
    orchestrator: claude-opus-4-6
    worker: claude-sonnet-4-6
    validator: claude-sonnet-4-6
  ```
- `ModelRouter` reads from workflow config with hardcoded defaults as fallback.
- `shux delegate --role <role>` passes resolved model to the dispatch runner.
- `shux delegate` without `--role` defaults to `worker`.

#### Refactor

- Expose `shux model-routing show` to print current resolved presets.
- Add validation: unknown model strings emit a warning (not a hard error) to allow
  future model IDs without breaking existing configs.

#### E2E test

```python
# tests/integration/test_model_routing_dispatch.py

def test_dispatch_uses_workflow_model_for_role(tmp_project):
    shux("workflow set model_routing.validator claude-haiku-4-5-20251001")
    tid = advance_to_review(tmp_project)
    dispatch = shux_json(f"delegate {tid} --role validator --dry-run")
    assert dispatch["model"] == "claude-haiku-4-5-20251001"
```

---

### Iter 4 — Parallel code-review subagents within validator

**What:** when a validator runs, fan out one code-review subagent per completed feature
in the milestone. Collect results, merge findings, then produce the single validator
verdict. Feature execution remains serial; review is parallel and read-only.

**Why:** validator wall-clock time is the dominant cost in a mission. Code review is
embarrassingly parallel (read-only, no shared writes).

#### Red

```python
# tests/unit/test_parallel_review_fanout.py

def test_fanout_spawns_one_agent_per_feature(db):
    milestone = create_milestone_with_features(db, n=3)
    jobs = build_review_fanout(db, milestone.id)
    assert len(jobs) == 3
    for job in jobs:
        assert job["role"] == "code_reviewer"
        assert job["read_only"] is True

def test_fanout_results_merged_into_single_verdict(db, mocker):
    milestone = create_milestone_with_features(db, n=3)
    fake_results = [{"passed": True}, {"passed": False, "findings": ["X"]}, {"passed": True}]
    mocker.patch("superharness.validator.run_fanout", return_value=fake_results)
    verdict = merge_review_results(fake_results)
    assert verdict["passed"] is False
    assert "X" in verdict["findings"]
```

#### Green

- Add `ReviewFanout` class: takes a milestone, builds one dispatch job per feature.
- Each job: `--role code_reviewer`, `--read-only`, passes only the feature diff and
  locked contract slice for that feature.
- `FanoutRunner`: submits all jobs concurrently (thread pool, max workers = 4),
  collects results, calls `merge_review_results()`.
- `merge_review_results()`: `passed = all(r["passed"] for r in results)`,
  aggregated `findings` list.
- Validator phase calls `FanoutRunner` instead of a single review agent.

#### Refactor

- Make max workers configurable via `workflow set review_fanout.max_workers N`.
- Add `shux insights` output: `avg_review_fanout_duration`, `avg_reviews_per_milestone`.

#### E2E test

```python
# tests/integration/test_parallel_review.py

def test_milestone_review_runs_in_parallel(tmp_project):
    """Three features reviewed concurrently; total time < sum of serial times."""
    milestone_id = create_milestone_with_n_features(tmp_project, 3)
    t0 = time.monotonic()
    result = shux_json(f"validate-milestone {milestone_id}")
    elapsed = time.monotonic() - t0
    assert result["review_count"] == 3
    # Each review takes ~1s in stub mode; parallel = ~1s total, serial = ~3s
    assert elapsed < 2.5
```

---

### Iter 5 — Behavioral validator (experimental)

**What:** a script-driven validator agent that starts the superharness dashboard, drives
it via HTTP (or headless browser), and verifies that defined behavioral assertions pass.
Not full computer use — scoped to the dashboard and CLI flows superharness already
exposes.

**Why:** functional regressions in long-running tasks are only caught by a human
reviewing a report. A behavioral validator catches them at milestone boundaries.

#### Red

```python
# tests/unit/test_behavioral_validator.py

def test_behavioral_plan_parsed_from_contract(db):
    contract = {"behavioral_assertions": [
        {"action": "GET /api/status", "expect_status": 200},
        {"action": "POST /api/task", "body": {...}, "expect_status": 201},
    ]}
    plan = BehavioralValidator.parse_plan(contract)
    assert len(plan.steps) == 2
    assert plan.steps[0].action == "GET /api/status"

def test_behavioral_step_failure_produces_finding(mocker):
    mocker.patch("requests.get", return_value=Mock(status_code=500))
    step = BehavioralStep(action="GET /api/status", expect_status=200)
    result = step.run("http://localhost:8787")
    assert result.passed is False
    assert "500" in result.finding
```

#### Green

- Add `behavioral_assertions` optional key to validation contract schema.
- `BehavioralValidator`: parses assertions from locked contract, executes HTTP steps
  against a locally started dashboard instance, returns pass/fail per step.
- Validator phase runs `BehavioralValidator` after scrutiny validator if assertions
  are present.
- Dashboard startup: reuse `ThreadingHTTPServer` pattern from test fixtures.

#### Refactor

- Extract `DashboardDriver` so behavioral tests and integration tests share the same
  in-process server setup (eliminate duplication with `test_dashboard_logs_stream.py`).

#### E2E test

```python
# tests/integration/test_behavioral_validator.py

def test_behavioral_validator_catches_broken_api(tmp_project):
    """Behavioral validator fails when dashboard returns wrong status."""
    contract = {
        "behavioral_assertions": [
            {"action": "GET /api/status", "expect_status": 200},
        ]
    }
    tid = create_task_with_contract(tmp_project, contract)
    advance_to_review(tmp_project, tid)
    result = shux_json(f"validate-behavioral {tid}")
    assert result["steps"][0]["action"] == "GET /api/status"
    # Will pass against a live dashboard, fail if port closed
```

---

## Delivery Order

```
Iter 1  Contract lock           (zero new infra — highest leverage)
Iter 2  Fresh-context dispatch  (needs worktree support — already shipped in v1.14)
Iter 3  Model routing           (config + router class — low risk)
Iter 4  Parallel review fanout  (thread pool + merge logic)
Iter 5  Behavioral validator    (experimental — dashboard driver reuse)
```

Each iter is independently shippable. Iter 1 can land in a single PR.
Iters 2–4 can be batched if bandwidth allows.
Iter 5 is a spike — time-box to one session before committing.
