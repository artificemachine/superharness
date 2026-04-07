# Task Workflow v2 — Implementation Plan

## Context

superharness tasks currently use a rigid template with hardcoded development methods (tdd/bdd/sdd/none), no test type selection, no explicit model assignment, and no timeout control. The orchestrator (Opus) decomposes tasks but only reads id/title/acceptance_criteria — ignoring effort, method, scope boundaries, and context.

This plan enhances the task workflow with flexible fields, explicit model routing, timeout safety, method-aware decomposition, and resilience features. All changes are backward-compatible with the 59 existing done tasks.

---

## Phase 1 — Task Fields

### Files
- `src/superharness/engine/schemas.py`
- `src/superharness/commands/task.py`
- `src/superharness/engine/validate.py`

### Changes

**schemas.py — ContractTask:**
```python
class ContractTask(BaseModel):
    # ... existing fields ...

    # RENAMED: tdd → plan (alias for backward compat)
    plan: Optional[dict] = Field(None, alias="tdd")

    # NEW fields
    effort: Optional[str] = "medium"           # low | medium | high | max
    test_types: Optional[list[str]] = None      # free-form: unit, integration, e2e, security, etc.
    out_of_scope: Optional[list[str]] = None
    definition_of_done: Optional[list[str]] = None
    context: Optional[str] = None               # operator-authored, injected into dispatch prompt

    # RENAMED: deadline_minutes → timeout_minutes
    timeout_minutes: Optional[int] = None       # auto-derived from model+effort if not set
    progress_timeout_minutes: Optional[int] = 10
```

**schemas.py — Contract (project-level default):**
```python
class Contract(BaseModel):
    # ... existing fields ...
    default_definition_of_done: Optional[list[str]] = None
```

**task.py:**
- Remove `VALID_DEVELOPMENT_METHODS` hardcoded enum — accept any string
- Add `--test-types` flag (comma-separated, stored as list)
- Add `--effort` flag (low/medium/high/max, default medium)
- Add `--out-of-scope` flag (repeatable)
- Add `--definition-of-done` flag (repeatable)
- Add `--context` flag (string)
- Add `--timeout-minutes` flag (int, optional)
- Rename `--tdd-red/green/refactor` → keep as aliases, add generic `--plan-step KEY=VALUE` (repeatable)
- Add method-specific shorthand flags:
  - `--bdd-given`, `--bdd-when`, `--bdd-then`
  - `--atdd-acceptance`, `--atdd-implement`, `--atdd-verify`
  - `--sdd-spec`, `--sdd-design`, `--sdd-implement`

**validate.py:**
- Read `plan` field (with `tdd` fallback for old contracts)
- Read `definition_of_done` or inherit from contract `default_definition_of_done`
- Warn if `effort: high/max` task has no `out_of_scope`

### Backward Compatibility
- Pydantic `Field(alias="tdd")` + `populate_by_name=True` means:
  - Old contracts with `tdd:` key → read into `plan` field
  - New contracts write `plan:` key
  - Both work at read time
- `deadline_minutes` → `timeout_minutes`: old field unused, no migration needed

---

## Phase 2 — Model Fields

### Files
- `src/superharness/engine/schemas.py`
- `src/superharness/engine/model_router.py`
- `src/superharness/engine/cost_estimator.py`
- `src/superharness/engine/orchestrator.py`
- `src/superharness/commands/task.py`
- `src/superharness/commands/delegate.py`

### Changes

**schemas.py — ContractTask:**
```python
class ContractTask(BaseModel):
    # NEW: replace model_tier with direct model + version
    model: Optional[str] = None                 # haiku | sonnet | opus
    model_version: Optional[str] = "*"          # * | 4.5 | 4.6
```

**schemas.py — Subtask:**
```python
class Subtask(BaseModel):
    model: str = "sonnet"                       # replaces model_tier
    model_version: str = "*"
    model_id: Optional[str] = None              # resolved full ID (claude-sonnet-4-6)
    effort: str = "medium"
    timeout_minutes: Optional[int] = None
    # keep model_tier as Optional for backward compat reads
    model_tier: Optional[str] = None
```

**model_router.py:**
```python
VALID_MODELS = {"haiku", "sonnet", "opus"}
VALID_EFFORTS = {"low", "medium", "high", "max"}

MODEL_VERSIONS = {
    "haiku":  {"*": "claude-haiku-4-5-20251001", "4.5": "claude-haiku-4-5-20251001"},
    "sonnet": {"*": "claude-sonnet-4-6",          "4.6": "claude-sonnet-4-6"},
    "opus":   {"*": "claude-opus-4-6",            "4.6": "claude-opus-4-6"},
}

# Timeout matrix (minutes): model x effort → default timeout (5–30 min)
TIMEOUT_MATRIX = {
    ("haiku",  "low"): 5,   ("haiku",  "medium"): 10,  ("haiku",  "high"): 15,  ("haiku",  "max"): 20,
    ("sonnet", "low"): 10,  ("sonnet", "medium"): 15,  ("sonnet", "high"): 20,  ("sonnet", "max"): 25,
    ("opus",   "low"): 15,  ("opus",   "medium"): 20,  ("opus",   "high"): 25,  ("opus",   "max"): 30,
}

def resolve_model_id(model: str, version: str = "*") -> str:
    """Resolve model family + version to full model ID."""
    return (MODEL_VERSIONS.get(model, {}).get(version)
            or MODEL_VERSIONS.get(model, {}).get("*")
            or "claude-sonnet-4-6")

def resolve_timeout(model: str, effort: str) -> int:
    """Resolve default timeout from model x effort matrix."""
    return TIMEOUT_MATRIX.get((model, effort), 15)

def auto_pin_version(model: str, effort: str) -> str:
    """Auto-pin model_version for high/max effort, * otherwise."""
    if effort in ("high", "max"):
        versions = MODEL_VERSIONS.get(model, {})
        return next((v for v in versions if v != "*"), "*")
    return "*"
```

- Remove `MODEL_MAP`, `VALID_TIERS`, `ModelTier` enum
- `classify_task()` returns `(model, effort)` instead of `(tier, effort)`
- `resolve_model()` → `resolve_model_id()`
- Keep `MODEL_MAP` as deprecated alias for any external consumers

**cost_estimator.py:**
- Accept `model` (haiku/sonnet/opus) instead of `tier` (mini/standard/max)
- Resolve via `MODEL_VERSIONS` → `MODEL_PRICING`

**delegate.py:**
- Model resolution order: CLI flag → task field → auto-classify → profile default → fallback
- Inject `task.context` into dispatch prompt alongside `_build_context_hint()` output
- Use `resolve_timeout()` for `--launcher-timeout` when not set explicitly

---

## Phase 3 — Orchestrator Enhancement

### Files
- `src/superharness/engine/orchestrator.py`

### Changes

**Updated _DECOMPOSE_PROMPT** — feed all new fields:
```
Task:
  ID: {task_id}
  Title: {title}
  Effort: {effort}
  Development method: {development_method}
  Test types: {test_types}
  Acceptance criteria: {criteria}
  Out of scope: {out_of_scope}
  Definition of done: {definition_of_done}
  Context: {context}

Models (use the model name, not a tier):
- haiku ($0.25/$1.25/MTok): docs, config, boilerplate, schema, single-file
- sonnet ($3/$15/MTok): multi-file, refactoring, debugging, tests, features
- opus ($15/$75/MTok): architecture, security, cross-system, 5+ constraints

Effort levels: low, medium, high, max

Rules:
1. Split decision: If effort=low, do NOT split — return single subtask.
   If effort=medium, split only if AC>3 or task touches >4 files.
   If effort=high/max, always evaluate splitting.
2. Subtask IDs: <parent_id>.<N>
3. If development_method is set, structure subtasks around the method phases
   (tdd: red/green/refactor, bdd: given/when/then, etc.)
4. Respect out_of_scope — no subtask should violate boundaries
5. Assign model, model_version, effort, timeout_minutes to each subtask
6. Add blocked_by between sequential subtasks

Reply with JSON:
{
  "should_split": true|false,
  "rationale": "why split or not",
  "subtasks": [
    {
      "id": "<parent>.<N>",
      "title": "...",
      "model": "haiku|sonnet|opus",
      "model_version": "*|4.5|4.6",
      "effort": "low|medium|high|max",
      "timeout_minutes": <int>,
      "blocked_by": "<parent>.<N-1>" or null,
      "plan": { ... method-specific phases ... },
      "estimated_tokens": <int>
    }
  ]
}
```

**Subtask dependency ordering:**
- Orchestrator outputs `blocked_by` per subtask
- Written to contract.yaml subtasks list
- Watcher respects ordering: only dispatch subtask N when N-1 is done

---

## Phase 4 — Resilience

### Files
- `src/superharness/engine/schemas.py`
- `src/superharness/commands/task.py`
- `src/superharness/engine/inbox.py`
- `src/superharness/commands/inbox_watch.py`

### Changes

**schemas.py — ContractTask:**
```python
class ContractTask(BaseModel):
    # NEW resilience fields
    retry_escalation: Optional[bool] = False    # step up effort on each retry
    on_timeout: Optional[str] = "retry"         # retry | fail | pause | notify
    on_failure: Optional[str] = "retry"         # retry | fail | pause | escalate
```

**task.py:**
- Add `--retry-escalation` flag (bool)
- Add `--on-timeout` flag (retry/fail/pause/notify)
- Add `--on-failure` flag (retry/fail/pause/escalate)

**inbox.py / inbox_watch.py:**
- On timeout: read task.on_timeout → execute action
- On failure: read task.on_failure → execute action
- `retry_escalation=true`: bump effort (low→medium→high→max) on each retry
  - Also bump model if effort was already max (sonnet→opus)
- `on_timeout: pause` → set inbox status=paused, notify owner
- `on_failure: escalate` → bump model, re-enqueue
- `progress_timeout_minutes`: watcher checks ledger mtime while status=running
  - If no ledger write in N minutes → treat as stuck → apply on_timeout action

---

## Phase 5 — install_hooks fix (already done)

### Files
- `src/superharness/commands/install_hooks.py`

### Changes (done)
- `merge_hooks()` only updates hook path if existing path doesn't exist on disk
- `--force` flag to always overwrite
- `install_hooks()` accepts `force: bool = False` param

---

## Task YAML Templates

### Minimal task (quick workflow)
```yaml
- id: fix.typo-readme
  title: Fix typo in README
  owner: claude-code
  status: todo
  effort: low
```

### Standard feature (TDD)
```yaml
- id: feat.user-search
  title: Add full-text user search endpoint
  owner: claude-code
  status: todo
  effort: medium
  model: sonnet
  model_version: "*"
  development_method: tdd
  test_types: [unit, integration]
  acceptance_criteria:
    - GET /users/search?q= returns matching users
    - results are paginated (20 per page)
    - empty query returns 400
  plan:
    red: write test for search endpoint with mock data
    green: implement search with LIKE query + pagination
    refactor: extract pagination to shared util
  definition_of_done:
    - all tests pass
    - no new shipguard warnings
```

### BDD feature
```yaml
- id: feat.checkout-flow
  title: Implement checkout with Stripe
  owner: claude-code
  status: todo
  effort: high
  model: sonnet
  model_version: "4.6"
  development_method: bdd
  test_types: [unit, integration, e2e, contract]
  acceptance_criteria:
    - user can add items to cart and checkout
    - payment is processed via Stripe
    - confirmation email is sent
  plan:
    given: user has items in cart and valid payment method
    when: user clicks checkout
    then: payment is charged, order is created, email is sent
  out_of_scope:
    - no guest checkout (must be logged in)
    - do not modify existing cart model
  context: |
    Stripe keys are in .env (STRIPE_SECRET_KEY).
    Cart model is in src/models/cart.py — read it first.
    See handoff feat.cart-v1-to-owner.yaml for prior decisions.
```

### Complex task (Opus, with orchestrator split)
```yaml
- id: feat.oauth2-auth
  title: Add OAuth2 authentication to the REST API
  owner: claude-code
  status: todo
  effort: max
  model: opus
  model_version: "4.6"
  development_method: tdd
  test_types: [unit, integration, security, contract]
  timeout_minutes: 30
  progress_timeout_minutes: 10
  retry_escalation: true
  on_timeout: pause
  on_failure: escalate
  acceptance_criteria:
    - users can authenticate via GitHub and Google OAuth2
    - tokens are validated on every protected endpoint
    - expired tokens return 401 with a refresh hint
    - all auth events are written to the audit log
    - brute-force attempts are rate-limited after 5 failures
  plan:
    red: write tests for token validation, rate limiting, audit log
    green: implement OAuth2 flow, JWT middleware, rate limiter
    refactor: extract auth service, unify provider interface
  out_of_scope:
    - no UI login page
    - do not modify existing user model fields
  definition_of_done:
    - all tests pass
    - no new shipguard warnings
    - CHANGELOG.md updated
    - API docs updated
  context: |
    Auth middleware lives in src/api/middleware/.
    Session token format changed in PR #82 — use new shape.
    Read handoff feat.adapter-registry-v1-instructions.md for context.
```

### After Opus orchestrator split
```yaml
- id: feat.oauth2-auth
  # ... parent task fields above ...
  subtasks:
    - id: feat.oauth2-auth.1
      title: Add OAuth2 config schema and provider settings
      model: haiku
      model_version: "*"
      model_id: claude-haiku-4-5-20251001
      effort: low
      timeout_minutes: 5
      plan:
        red: schema validation test for missing client_id/secret
        green: add OAuthProvider dataclass + load from env
        refactor: extract to dedicated config module
      estimated_tokens: 8000

    - id: feat.oauth2-auth.2
      title: Implement OAuth2 provider exchange
      model: sonnet
      model_version: "4.6"
      model_id: claude-sonnet-4-6
      effort: medium
      timeout_minutes: 15
      blocked_by: feat.oauth2-auth.1
      plan:
        red: mock provider returns token, assert user profile parsed
        green: implement authorization code exchange for GitHub + Google
        refactor: unify provider interface behind OAuthProvider ABC
      estimated_tokens: 35000

    - id: feat.oauth2-auth.3
      title: JWT validation middleware + endpoint guards
      model: sonnet
      model_version: "4.6"
      model_id: claude-sonnet-4-6
      effort: medium
      timeout_minutes: 15
      blocked_by: feat.oauth2-auth.2
      plan:
        red: request with expired token returns 401 + refresh hint
        green: decode + validate JWT, attach user to request context
        refactor: move guard logic to decorator
      estimated_tokens: 30000

    - id: feat.oauth2-auth.4
      title: Rate limiting, timing-safe comparison, audit logging
      model: opus
      model_version: "4.6"
      model_id: claude-opus-4-6
      effort: max
      timeout_minutes: 30
      blocked_by: feat.oauth2-auth.3
      plan:
        red: timing attack test, lockout after 5 failures, audit log captures
        green: sliding-window rate limiter, hmac.compare_digest, structured audit
        refactor: extract rate limiter to middleware, audit log to service
      estimated_tokens: 55000

    - id: feat.oauth2-auth.5
      title: API docs + CHANGELOG entry
      model: haiku
      model_version: "*"
      model_id: claude-haiku-4-5-20251001
      effort: low
      timeout_minutes: 5
      blocked_by: feat.oauth2-auth.4
      plan:
        red: doc coverage check fails (missing /auth endpoints)
        green: add OAuth2 section to API reference, update CHANGELOG
        refactor: ~
      estimated_tokens: 6000
```

### Task with project-level DoD inheritance
```yaml
# contract.yaml header
id: sprint-42
created: 2026-04-07
created_by: owner
status: active
goal: Ship OAuth2 + search
default_definition_of_done:
  - all tests pass
  - no new shipguard warnings
  - CHANGELOG.md updated

tasks:
  - id: fix.typo-readme
    title: Fix typo
    owner: claude-code
    status: todo
    effort: low
    # inherits default_definition_of_done — no need to repeat

  - id: feat.oauth2-auth
    title: Add OAuth2 auth
    owner: claude-code
    status: todo
    effort: max
    definition_of_done:
      - all tests pass
      - no new shipguard warnings
      - CHANGELOG.md updated
      - API docs updated
      - security review passed
    # overrides project default — adds extra gates
```

---

## Implementation Order

```
Phase 5 (install_hooks fix) — already done, ship first
    |
Phase 1 (task fields) — foundation, no external dependencies
    |
Phase 2 (model fields) — depends on Phase 1 (effort field)
    |
Phase 3 (orchestrator) — depends on Phase 1 + 2 (reads all new fields)
    |
Phase 4 (resilience) — depends on Phase 2 + 3 (timeout wiring, escalation)
```

Each phase is independently shippable. Phase 5 is already done and can go out immediately.

---

## Test Plan

### Phase 1 tests
- `test_task_create_with_test_types` — verify comma-separated list in contract
- `test_task_create_with_effort` — verify effort values written correctly
- `test_task_create_with_plan_bdd` — verify --bdd-given/when/then write to plan dict
- `test_task_create_development_method_any_string` — verify no hardcoded enum rejection
- `test_plan_field_reads_old_tdd_alias` — load contract with `tdd:` key, verify `plan` field populated
- `test_contract_default_definition_of_done` — verify inheritance at validate time
- `test_out_of_scope_written` — verify list stored in contract
- `test_context_field_written` — verify string stored in contract

### Phase 2 tests
- `test_resolve_model_id` — haiku/* → claude-haiku-4-5-20251001
- `test_resolve_model_id_pinned` — sonnet/4.6 → claude-sonnet-4-6
- `test_resolve_timeout_matrix` — all 12 combos return expected minutes
- `test_auto_pin_version` — high/max → pinned, low/medium → *
- `test_subtask_model_field` — verify model/model_version/model_id written to subtask
- `test_cost_estimator_by_model_name` — haiku/sonnet/opus accepted (not mini/standard/max)

### Phase 3 tests
- `test_orchestrator_split_decision_low` — effort:low → should_split=false
- `test_orchestrator_split_decision_high` — effort:high, 5 AC → should_split=true
- `test_orchestrator_method_aware_tdd` — subtasks follow red/green/refactor phases
- `test_orchestrator_method_aware_bdd` — subtasks follow given/when/then phases
- `test_orchestrator_subtask_blocked_by` — sequential ordering written
- `test_orchestrator_out_of_scope_injected` — prompt includes out_of_scope text

### Phase 4 tests
- `test_retry_escalation_bumps_effort` — low→medium on retry
- `test_retry_escalation_bumps_model` — max effort + retry → sonnet→opus
- `test_on_timeout_pause` — inbox item marked paused, not auto-retried
- `test_on_failure_escalate` — model bumped + re-enqueued
- `test_progress_timeout_stuck_detection` — no ledger write → stuck signal

---

## Verification

After all phases:
```bash
pytest tests/ -q                           # all tests pass
shux task create --id test-v2 \
  --title "Test new workflow" \
  --effort high \
  --model sonnet \
  --test-types unit,integration \
  --development-method tdd \
  --tdd-red "write failing test" \
  --tdd-green "implement" \
  --tdd-refactor "clean up" \
  --out-of-scope "no UI changes" \
  --context "Read src/api/ first"          # task created with all new fields
shux contract                              # verify new fields visible
shux delegate test-v2 --print-only         # verify prompt includes context + model
shux demo                                  # demo runs clean, no hook clobbering
```
