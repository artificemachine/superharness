# Plan — Effort Taxonomy v2, Opus 4.7, Decomposer Flow, Morpheme Nodes

**Status:** draft — §10 decisions resolved, ready for `plan_proposed` handoff
**Author:** claude-code
**Date:** 2026-04-17
**Supersedes sections of:** `docs/plan-task-workflow-v2.md` (Phase 1 effort list, Phase 2 model IDs)
**Related specs:** `docs/adapter-payload-spec.md`, `docs/adapter-models.md`, `docs/plan-task-workflow-v2.md`

---

## 1. Context

The task template, model router, schemas, adapter manifest, and docs reference:
- Effort levels `{low, medium, high, max}` (or worse, `{low, medium, high}` in three places)
- Opus pinned to `claude-opus-4-6`
- Haiku as the `mini` tier

Reality as of 2026-04-17:
- Claude Code UI exposes **five** effort levels: `low | medium | high | xhigh | max`
- Current session runs on **Opus 4.7** (`claude-opus-4-7`, also available as `claude-opus-4-7[1m]` for 1M context)
- Project direction: **drop Haiku** from the active model tier set; Sonnet 4.6 is the new floor

This document captures the taxonomy, model defaults, decomposer flow, and Morpheme node topology decided in session 2026-04-17. It is the input to a `plan_proposed` handoff, not the handoff itself.

---

## 2. Effort taxonomy — 5 levels, additive

| Effort | Purpose | Default model | Thinking budget | Default timeout |
|---|---|---|---|---|
| `low` | bounded scope, short output, low ambiguity | `claude-sonnet-4-6` | minimal | 10 min |
| `medium` | typical coding task, some judgment | `claude-sonnet-4-6` | adaptive, modest | 15 min |
| `high` | complex reasoning, multiple constraints, edge cases | `claude-sonnet-4-6` | adaptive, deep | 20 min |
| `xhigh` | cross-system tradeoffs, security-adjacent, subtle concurrency | `claude-opus-4-6` | adaptive, deep | 25 min |
| `max` | architecture / irreversible / highest-stakes | `claude-opus-4-7` | max | 30 min |

Two orthogonal axes:
- **Model** — 3 distinct choices (Sonnet 4.6 / Opus 4.6 / Opus 4.7)
- **Effort** — 5 runtime profiles driving thinking budget + timeout + orchestrator-split threshold

5 efforts × 3 models ≠ 15 combos; the default mapping is 1:1 per the table above. Operators can still pin `model` independently in `contract.yaml` to override.

### 2.1 Retry escalation ladder

`auto_dispatch.py` retries bump effort one step:

```
low → medium → high → xhigh → max
```

Model follows the table above. Escalation never skips a rung. `xhigh → max` also swaps `opus-4-6 → opus-4-7`.

---

## 3. Model IDs, versions, and 1M context

### 3.1 Canonical adapter manifest (target state)

`src/superharness/adapter_manifests/claude-code.yaml`:

```yaml
model_tiers:
  standard:
    versions:
      "*":   { id: claude-sonnet-4-6, label: "Sonnet 4.6" }
      "4.6": { id: claude-sonnet-4-6, label: "Sonnet 4.6" }
      "4.5": { id: claude-sonnet-4-5, label: "Sonnet 4.5" }
  max:
    versions:
      "*":   { id: claude-opus-4-7,   label: "Opus 4.7" }
      "4.7": { id: claude-opus-4-7,   label: "Opus 4.7" }
      "4.6": { id: claude-opus-4-6,   label: "Opus 4.6" }
  max-1m:  # 1M context beta — effort=max only; input>200K auto-promotes here
    versions:
      "*":   { id: "claude-opus-4-7[1m]", label: "Opus 4.7 (1M)" }
```

**3 tier slots only** (`standard`, `max`, `max-1m`). Effort drives *version* selection within `max`, not a separate tier. `xhigh` resolves to `max/"4.6"`; `max` resolves to `max/"*"` (→ `"4.7"`).

### 3.1.1 Effort → tier + version mapping

```python
# engine/taxonomy.py — single source of truth
EFFORT_TO_TIER_VERSION = {
    "low":    ("standard", "*"),    # → claude-sonnet-4-6
    "medium": ("standard", "*"),    # → claude-sonnet-4-6
    "high":   ("standard", "*"),    # → claude-sonnet-4-6
    "xhigh":  ("max",      "4.6"),  # → claude-opus-4-6
    "max":    ("max",      "*"),    # → claude-opus-4-7
    # max-1m tier reached via auto-promotion (§3.3) — not mapped from effort directly
}
```

### 3.2 Verified accepted IDs (probed against local CLI 2026-04-17)

```
claude-sonnet-4-5     ✅
claude-sonnet-4-6     ✅
claude-opus-4-6       ✅
claude-opus-4-7       ✅
claude-opus-4-7[1m]   ✅
```

### 3.3 1M context auto-promotion

```python
def should_use_1m_context(task, estimated_input_tokens):
    if task.effort != "max":
        return False
    if task.get("context_1m") is True:          # operator override
        return True
    return estimated_input_tokens > 200_000     # auto-trigger
```

Pricing note: Anthropic API charges ~2× input / 1.5× output on prompts over 200K under the 1M beta. Auto-promotion only for `effort=max` prevents silent budget blowouts.

Three operator paths to land on `claude-opus-4-7[1m]`:
1. Auto (estimator > 200K)
2. `shux delegate <id> --1m-context` (per-dispatch flag)
3. `context_1m: true` on the contract task (per-task pin)

---

## 4. Decomposer flow

### 4.1 Two distinct roles

| Role | Who | When | Cost per call |
|---|---|---|---|
| **Classifier** (router) | Sonnet 4.6 low-effort, or heuristics | operator didn't set `effort` | ~$0.002 |
| **Decomposer** (orchestrator) | Opus 4.6 | `effort ∈ {xhigh, max}` OR `--orchestrate` flag | ~$0.08–$0.30 |
| **Executor** (worker) | Sonnet 4.6 mostly, Opus only where earned | actual task / subtask work | varies |

Opus is **only the decomposer**. It is not automatically the parent task's executor.

### 4.2 Full dispatch pipeline

Sonnet LLM classifier is **opt-in** via `profile.yaml: auto_classify: true`. Default path uses heuristics only, falling through to `medium` on ambiguity.

```
shux delegate <id>
  │
  ├─ task.effort set by operator? ──yes──→ skip classifier
  │
  └─ no ──→ heuristic_classify() ──decisive──→ use result
                                 │
                                 └─ambiguous──→ profile.auto_classify?
                                                   │
                                                   ├─ true  → llm_classify() (Sonnet 4.6 low, ~$0.002)
                                                   └─ false → default to effort="medium" + warn
  │
  ▼
apply_safety_floor()   # AC count, file count, budget guard, 1M auto-promote
  │
  ├─ effort ∈ {low, medium, high} ──→ dispatch_direct() on sonnet-4-6
  │
  └─ effort ∈ {xhigh, max} ──→ opus_decomposer(task)
                                    │
                                    ├─ should_split=false ──→ dispatch_direct(parent.model, parent.effort)
                                    │
                                    └─ should_split=true ──→ spawn N subtasks (each with model+effort+blocked_by)
                                                             → dispatch_parallel(subtasks, respecting DAG)
```

Profile flag:

```yaml
# .superharness/profile.yaml
auto_classify: false  # default — heuristics + warn-default-medium
# auto_classify: true  # opt-in — Sonnet LLM fills in ambiguous cases (~$0.002/call)
```

### 4.3 Classifier — Stage 1: deterministic heuristics

No LLM call. Catches ~70% of tasks.

Hard triggers for `(opus-4-6, xhigh)`:
- Title / context contains any of: `architecture`, `migration`, `schema change`, `rewrite`, `oauth`, `auth`, `security audit`, `threat model`, `rbac`, `encryption`, `cryptographic`, `consensus`, `distributed`, `compliance`, `iec 62304`, `hipaa`, `gdpr`, `production deploy`, `irreversible`, `breaking change`
- `acceptance_criteria` count > 7
- referenced file count > 10
- `test_types` includes `security` AND `acceptance_criteria` count > 3

Hard escalation to `(opus-4-7, max)`:
- `retry_count > 0` AND previous attempt used `opus-4-6`

Hard triggers for `(sonnet-4-6, low)`:
- Title starts with `fix.typo`, `docs:`, `chore:` AND `acceptance_criteria` count ≤ 2

Hard triggers for `(sonnet-4-6, medium)`:
- `test_types == ["unit"]` AND file count ≤ 2

Otherwise → escalate to Stage 2.

### 4.4 Classifier — Stage 2: Sonnet LLM fallback

Prompt kept tight; response must be exactly two tokens.

```
You are a model router. Decide which model+effort handles this task best.

Models:
- sonnet-4-6: multi-file coding, refactoring, debugging, tests, features, API integration
- opus-4-6:   5+ interdependent constraints, cross-domain judgment, subtle concurrency, security review
- opus-4-7:   architecture design, irreversible decisions, novel system design, compliance

Effort: low | medium | high | xhigh | max
(low=bounded; medium=typical; high=complex; xhigh=cross-system; max=highest-stakes)

Task:
  Title: {title}
  Acceptance criteria: {criteria}
  Files: {files}
  Test types: {test_types}
  Out of scope: {out_of_scope}
  Context: {context}
  Previously failed: {failed}

Reply with exactly: <model> <effort>
Example: "sonnet-4-6 medium"
```

Runs with `max_tokens=20`, effort=`low`. Typical cost: ~$0.002 per call.

### 4.5 Classifier — Stage 3: safety floor

Applied to both heuristic and LLM results:
- If file count > 6 AND model == `sonnet-4-6` → bump effort to at least `high`
- If estimated cost > `project.budget.daily_remaining` → downgrade one step, log warning
- If `effort == max` AND estimated tokens > 200K → set `resolved_model = claude-opus-4-7[1m]`

### 4.6 Decomposer prompt (Opus 4.6)

Only runs when classifier landed on `xhigh` or `max`. Reads full task context and outputs JSON.

```
Task:
  ID:                  {task_id}
  Title:               {title}
  Effort:              {effort}
  Development method:  {development_method}
  Test types:          {test_types}
  Acceptance criteria: {criteria}
  Out of scope:        {out_of_scope}
  Definition of done:  {definition_of_done}
  Context:             {context}

Available executors (pick ONE per subtask):
- sonnet-4-6 ($3/$15 per MTok)   — default for ~80% of subtasks
- opus-4-6   ($15/$75 per MTok)  — complex core logic, security, cross-cutting concerns
- opus-4-7   ($15/$75 per MTok)  — reserve for the single irreversible subtask; max effort only

Rules:
1. Split decision:
   - effort=xhigh: evaluate split; typically 2–4 subtasks
   - effort=max: evaluate split; typically 3–6 subtasks
   - If AC ≤ 3 AND files ≤ 3 → do NOT split (return 1 subtask = original)
2. Subtask IDs: <parent_id>.<N>
3. If development_method is set, shape subtasks around its phases (tdd: red/green/refactor etc.)
4. Respect out_of_scope — no subtask may violate it
5. Assign model + effort + timeout per subtask using the table above
6. Use blocked_by for sequential ordering; leave independent subtasks unblocked
7. Subtask model MUST be ≤ parent model (never escalate silently)
8. Subtask effort MUST be ≤ parent effort (never escalate silently)
9. Prefer sonnet-4-6 unless the subtask explicitly requires Opus-level judgment

Reply with JSON:
{
  "should_split": true | false,
  "rationale": "...",
  "subtasks": [
    {
      "id": "<parent>.<N>",
      "title": "...",
      "model": "sonnet-4-6 | opus-4-6 | opus-4-7",
      "effort": "low | medium | high | xhigh | max",
      "timeout_minutes": <int>,
      "blocked_by": "<parent>.<N-1>" | null,
      "plan": { ... method-specific phases ... },
      "estimated_tokens": <int>
    }
  ]
}
```

### 4.6.1 Decomposer fallback when Opus 4.6 unavailable

If `claude-opus-4-6` is not available at dispatch time (API error, region restriction, quota exhausted), fall back to `claude-opus-4-7` with a warning log. Never fall back to Sonnet for decomposition — bad split decisions cascade into wasted executor cost downstream.

```python
DECOMPOSER_MODEL = "claude-opus-4-6"
DECOMPOSER_FALLBACK = "claude-opus-4-7"   # ~1.5× cost; log warning on use
DECOMPOSER_NEVER = "claude-sonnet-*"       # never fall back to Sonnet
```

### 4.8 Retry escalation ceiling

The retry ladder (`low → medium → high → xhigh → max`) terminates at `(claude-opus-4-7, max)`. A 3rd failure at this ceiling means the task has a **structural problem** — underspecified scope, contradictory acceptance criteria, missing context. Auto-escalating to `claude-opus-4-7[1m]` does not fix reasoning gaps; it just burns more tokens on the same confusion.

Behavior at the ceiling:

```python
def apply_retry_escalation(task):
    if task.retry_count >= 3 \
       and task.last_model == "claude-opus-4-7" \
       and task.effort == "max":
        task.status = "pending_user_approval"
        task.pause_reason = "3rd retry on opus-4-7 max — structural review needed"
        write_handoff(
            task,
            phase="stuck",
            diagnostics={
                "retry_history": task.retry_history,
                "last_error": task.last_error,
                "suggested_actions": [
                    "Split task manually into smaller scope",
                    "Add missing context / clarify AC",
                    "Opt-in to max-1m tier if input > 200K",
                ],
            },
        )
        notify_desktop(task, severity="high")
        return   # do not re-enqueue
    return escalate_one_step(task)
```

Operator can then:
- Manually bump to `max-1m` tier via `shux delegate <id> --1m-context`
- Decompose the task further by editing `acceptance_criteria` / `out_of_scope`
- Reject the task entirely (status → `failed`)

### 4.7 Subtask default matrix (what the decomposer picks)

| Parent effort | Subtask purpose | Default model | Default effort |
|---|---|---|---|
| `max` | boilerplate, CHANGELOG, docs | `sonnet-4-6` | `low` |
| `max` | unit tests, single-file impl | `sonnet-4-6` | `medium` |
| `max` | multi-file refactor, integration | `sonnet-4-6` | `high` |
| `max` | security / auth / core logic | `opus-4-6` | `xhigh` |
| `max` | the one irreversible architectural subtask | `opus-4-7` | `max` (inherits) |
| `xhigh` | boilerplate | `sonnet-4-6` | `low` |
| `xhigh` | standard impl | `sonnet-4-6` | `medium`/`high` |
| `xhigh` | complex core | `opus-4-6` | `xhigh` (inherits) |
| `high` | anything | `sonnet-4-6` | `low`/`medium`/`high` |
| `medium`/`low` | — | no split by default | — |

Rationale: default to Sonnet for ~80% of subtasks. Opus appears only on subtasks that earn it. Never silently escalate above the parent.

---

## 5. Morpheme node topology (adapter-payload → graph)

### 5.1 Chosen topology — conditional nodes

```
                  ┌─ effort=low/medium/high ─────────────────────────┐
                  │                                                  ▼
Operator ──→ Task ──→ Classifier* ──┐                           Executor ──→ Handoff
 (human)    (todo)   (Sonnet low)   │
                                    │                          ┌─→ Subtask.1 ─┐
                                    └─ effort=xhigh/max ─→ Decomposer         ├─→ Aggregated Handoff
                                                            (Opus 4.6)    ├─→ Subtask.2 ─┤
                                                                          └─→ Subtask.3 ─┘
                                                                              (DAG via blocked_by)
```

\* Classifier node collapses to a badge on Task when heuristics decided without an LLM call.

### 5.2 Conditional rendering rules

1. **Always render**: Operator, Task, Handoff
2. **Render Classifier** only if `task.classifier.invoked == true` (collapse to badge otherwise)
3. **Render Decomposer** only if `task.decomposer.invoked == true`
4. **Render Subtask nodes** only if `task.subtasks.length > 0`
5. **Render Executor node** only for direct-dispatch path (no subtasks)
6. **Render retry edge** only if `task.retry_count > 0`

### 5.3 Node palette

| Node | Shape | Color | Key content |
|---|---|---|---|
| Operator | rounded square | grey | actor name, timestamp |
| Classifier | small diamond | Sonnet blue | chosen effort + model, duration, $cost |
| Decomposer | hexagon | Opus purple | split rationale, #subtasks, $cost |
| Task | rectangle (large) | status color | id, title, effort badge, model badge, AC count |
| Subtask | rectangle (medium, visually nested) | status color | id, title, model badge, effort, blocked_by arrows |
| Executor | ghost / absorbed into Task or Subtask | — | runtime shown on containing node |
| Handoff | parallelogram | neutral | handoff file path, from/to, phase |

### 5.4 Status encoding

Applies to every runnable node (Task, Subtask, Decomposer, Classifier, Executor):

```
todo           ░░░ grey outline
plan_proposed  ░▓░ dashed grey
plan_approved  ▓▓▓ solid grey
in_progress    🟡 yellow + pulsing
report_ready   🔵 blue
review_passed  🟢 green
done           🟢 green filled
failed         🔴 red
stopped        ⚪ white + strikethrough
```

### 5.5 Edge semantics

| Edge | Meaning | Render |
|---|---|---|
| Operator → Task | authorship | solid, labeled with creation timestamp |
| Task → Classifier | dispatch trigger | solid |
| Classifier → Decomposer | "split needed" | solid, labeled with triggering effort |
| Classifier → Executor | "direct dispatch" | solid (shortcut path) |
| Decomposer → Subtask | spawn | solid, labeled with model/effort assigned |
| Subtask → Subtask | `blocked_by` | dashed, arrow = dependency order |
| Task/Subtask → Handoff | completion | solid, labeled with phase |
| Task → Task (retry) | retry_escalation | curved feedback loop, dashed, "model↑" label |

### 5.6 What the operator sees at a glance

- **Flat horizontal chain** = trivial task, one call, Sonnet
- **Hexagon in the middle** = decomposer ran, task was complex
- **Fan-out after the hexagon** = parallel subtasks, each with its own model badge
- **Dashed arrows between subtasks** = dependency ordering
- **Feedback loop arrow** = task was retried and escalated
- **Purple badges** = Opus dollars
- **Blue badges** = Sonnet dollars

---

## 6. Adapter-payload spec v1.2 delta

`shux adapter-payload --json` schema bump: `1.1 → 1.2`. Additive only; v1.1 consumers stay compatible.

### 6.1 New fields on each `task` (and each `subtask`)

```json
{
  "id": "feat.oauth2",
  "title": "...",
  "effort": "max",
  "resolved_model": { "id": "claude-opus-4-7", "label": "Opus 4.7" },

  "classifier": {
    "invoked": true,
    "decided_by": "sonnet-4-6" | "heuristic",
    "heuristic_reason": "title matches OPUS_KEYWORDS" | null,
    "cost_usd": 0.002,
    "duration_ms": 420
  },

  "decomposer": {
    "invoked": true,
    "model": "claude-opus-4-6",
    "rationale": "AC count=6, touches auth + db + api; split 4-way with blocked_by ordering",
    "cost_usd": 0.08,
    "duration_ms": 4200,
    "subtask_count": 4
  },

  "retry": {
    "count": 0,
    "escalation_history": []
  },

  "subtasks": [
    {
      "id": "feat.oauth2.1",
      "model": "sonnet-4-6",
      "effort": "low",
      "blocked_by": null,
      "resolved_model": { "id": "claude-sonnet-4-6", "label": "Sonnet 4.6" }
    }
    // ...
  ]
}
```

### 6.2 Morpheme node schema (JSON, consumed from payload)

Morpheme's renderer already maps `task` + `subtask` → nodes. New node kinds:

```typescript
type NodeKind =
  | "operator"
  | "classifier"     // NEW
  | "decomposer"     // NEW
  | "task"
  | "subtask"
  | "executor"       // NEW (usually ghost)
  | "handoff";

interface BaseNode {
  id: string;
  kind: NodeKind;
  status: TaskStatus;
  cost_usd?: number;
  duration_ms?: number;
  model?: { id: string; label: string };
  effort?: Effort;
}

interface ClassifierNode extends BaseNode {
  kind: "classifier";
  decided_by: "sonnet-4-6" | "heuristic";
  heuristic_reason?: string;
  chose_effort: Effort;
  chose_model: string;
}

interface DecomposerNode extends BaseNode {
  kind: "decomposer";
  model: {
    id: "claude-opus-4-6" | "claude-opus-4-7";   // 4-7 only when fallback used
    label: "Opus 4.6" | "Opus 4.7";
  };
  rationale: string;
  subtask_count: number;
  fallback_used: boolean;                         // true = Opus 4.6 unavailable
}

interface Edge {
  from: string;
  to: string;
  kind: "authorship" | "dispatch" | "spawn" | "blocked_by" | "completion" | "retry";
  label?: string;
  style: "solid" | "dashed";
}
```

### 6.3 Edge list derived from payload

Morpheme builds edges from payload fields — no new storage needed:
- `operator.id → task.id` (authorship)
- `task.id → classifier.id` if `classifier.invoked`
- `classifier.id → decomposer.id` if `decomposer.invoked`
- `decomposer.id → subtask.id` for each subtask
- `subtask[n-1].id → subtask[n].id` (dashed) for each `blocked_by`
- `task.id / subtask.id → handoff.id` (completion)
- `task.id → task.id` self-loop if `retry.count > 0`

### 6.4 Backward compatibility

- v1.1 consumers ignore the new `classifier`, `decomposer`, `retry` keys (extra fields tolerated)
- Payload `schema_version` string bumps to `"1.2"`
- Morpheme's `ADAPTER_SCHEMA_VERSION` stays on `"1.0"` for legacy path; add parallel support for `"1.2"` behind a feature flag until stable

---

## 7. Files that need touching (enumeration only, not diffs)

Implementation scope — enumerated so the plan handoff can decompose:

### 7.1 Effort taxonomy (add `xhigh`)
- `src/superharness/commands/task.py` — `VALID_EFFORTS`
- `src/superharness/commands/delegate.py` — `--effort` choices
- `src/superharness/commands/auto_dispatch.py` — `effort_order` + `choices`
- `src/superharness/engine/model_router.py` — `VALID_EFFORTS` + prompt
- `src/superharness/engine/validate.py` — `_VALID_EFFORTS`
- `src/superharness/engine/schemas.py` — `Profile.default_effort` Literal
- `protocol/templates/profile.schema.yaml` — `values:` list
- `docs/GUIDE.md` — two disagreeing lines
- `docs/adapter-payload-spec.md` — effort enum

### 7.2 Central taxonomy module (new)
- `src/superharness/engine/taxonomy.py` — single source of truth: `VALID_EFFORTS`, `EFFORT_ORDER`, `DEFAULT_MODEL_PER_EFFORT`, `DEFAULT_TIMEOUT_PER_EFFORT`, `OPUS_KEYWORDS`
- Re-imported by all sites above

### 7.3 Model updates (Opus 4.6 → 4.7)
- `src/superharness/adapter_manifests/claude-code.yaml` — new `standard` / `max` / `max-1m` tier structure (3 slots, versioned entries)
- `src/superharness/engine/sdk_runner.py` — `_MODEL_PRICING` + add `claude-opus-4-7`
- `src/superharness/engine/cost_estimator.py` — `_TIER_TO_MODEL`
- `src/superharness/cli.py` — `shortcuts` dict
- `src/superharness/engine/swarm.py` — `reviewer_model` default
- `docs/adapter-models.md` — table + rationale section
- `docs/plan-task-workflow-v2.md` — mark Phase 2 model list as superseded

### 7.4 Classifier refactor
- `src/superharness/engine/model_router.py` — heuristic + Sonnet LLM stages, drop Haiku
- `tests/unit/test_model_router.py` — new tests for heuristic triggers, safety floor, Sonnet fallback

### 7.5 Decomposer prompt refactor
- `src/superharness/engine/orchestrator.py` — new `_DECOMPOSE_PROMPT` with 5-effort scale and Sonnet/Opus-only menu
- `tests/unit/test_orchestrator.py` — update expected JSON schema

### 7.6 Adapter-payload v1.2
- `src/superharness/commands/adapter_payload.py` — emit `classifier`, `decomposer`, `retry` blocks
- `docs/adapter-payload-spec.md` — document new fields
- `tests/unit/test_adapter_payload.py` — new assertions

### 7.7 Morpheme-side (separate repo, out of scope here)
- `adapter.js` — add v1.2 schema version support
- renderer — `classifier`, `decomposer`, `executor` node kinds + edge rules

---

## 8. Test plan (TDD — RED phase checklist)

Before any implementation, write failing tests for:

### 8.1 Taxonomy
- `test_taxonomy_has_five_efforts` — `VALID_EFFORTS == {low, medium, high, xhigh, max}`
- `test_effort_order` — `EFFORT_ORDER` is a 5-element list in ascending order
- `test_default_model_per_effort` — each effort maps to expected model ID
- `test_xhigh_effort_accepted_by_task_create` — `shux task create --effort xhigh` succeeds

### 8.2 Model IDs
- `test_adapter_manifest_max_is_opus_47` — loader returns `claude-opus-4-7` for `max` tier
- `test_pricing_includes_opus_47` — `MODEL_PRICING["claude-opus-4-7"]` present
- `test_cli_shortcut_opus_resolves_to_4_7` — `--model opus` → `claude-opus-4-7`
- `test_1m_variant_accepted` — `claude-opus-4-7[1m]` round-trips through schema

### 8.3 Classifier
- `test_heuristic_promotes_on_opus_keyword` — title with "oauth" → `(opus-4-6, xhigh)`
- `test_heuristic_demotes_on_typo_fix` — title `fix.typo-readme` → `(sonnet-4-6, low)`
- `test_classifier_retry_escalation` — `retry_count>0` + prev `opus-4-6` → `opus-4-7, max`
- `test_sonnet_classifier_fallback` — ambiguous task hits LLM path (mocked)
- `test_safety_floor_budget_guard` — classifier downgrades when estimate > budget
- `test_1m_auto_promotion` — `effort=max` + tokens>200K → `claude-opus-4-7[1m]`

### 8.4 Decomposer
- `test_decomposer_not_invoked_for_low_medium_high` — no Opus call
- `test_decomposer_invoked_for_xhigh_max` — Opus call made
- `test_subtask_model_never_above_parent` — invariant enforced
- `test_subtask_effort_never_above_parent` — invariant enforced
- `test_subtask_default_is_sonnet` — ~80% of generated subtasks are `sonnet-4-6`

### 8.5 Adapter payload v1.2
- `test_payload_schema_version_bumped` — `"1.2"`
- `test_payload_includes_classifier_block_when_invoked`
- `test_payload_includes_decomposer_block_when_invoked`
- `test_payload_backward_compatible_with_v1_1_consumer` — extra fields ignored

---

## 9. Implementation order (decomposition preview for plan_proposed)

Each sub-plan is a separate task to keep `acceptance_criteria` ≤ 3 and files touched ≤ 4:

1. **`feat.taxonomy-module`** — create `engine/taxonomy.py`, migrate all 7 call sites one by one
   - RED: tests for the new module exist and fail
   - GREEN: module + minimal migrations pass
   - REFACTOR: delete duplicate `VALID_EFFORTS` literals
2. **`feat.opus-47-adapter`** — update adapter manifest + pricing + CLI shortcut
3. **`feat.1m-context-tier`** — add `ultra` tier + auto-promotion logic + tests
4. **`feat.classifier-v2`** — Sonnet-based classifier, heuristics, safety floor
5. **`feat.decomposer-prompt-v2`** — update orchestrator prompt, enforce subtask ≤ parent invariant
6. **`feat.adapter-payload-v1_2`** — emit classifier + decomposer blocks, spec + tests
7. **`docs.effort-taxonomy-docs`** — GUIDE.md + adapter-models.md + changelog

Morpheme-side node rendering (classifier/decomposer shapes, edge kinds) lives in a paired plan in the `morpheme` repo, not here.

---

## 10. Resolved decisions (2026-04-17)

All five open decisions resolved and folded into §3, §4, and §6 above.

| # | Decision | Resolution | Folded into |
|---|---|---|---|
| 1 | 1M-context tier name | **`max-1m`** (self-describing, scales to future 2M/4M) | §3.1 |
| 2 | `xmax` tier for `xhigh` effort | **Dropped** — `xhigh` resolves to `max/"4.6"` via version selection | §3.1, §3.1.1 |
| 3 | Classifier when `effort` unset | **Heuristics only by default**; Sonnet LLM opt-in via `auto_classify: true` | §4.2 |
| 4 | Decomposer fallback | **Opus 4.7** with warning log; never fall back to Sonnet | §4.6.1 |
| 5 | Retry ceiling | **Pause + notify operator** at 3rd failure on `opus-4-7 max` | §4.8 |

Result: 3 tier slots (`standard`, `max`, `max-1m`), 5 effort levels, deterministic effort→model mapping, bounded retry budget.

---

## 11. Non-goals

- Haiku tier removal from `adapter_manifests/*` — keep the tier slot, just stop using it as default. Haiku remains available for explicit `--model haiku` dispatch.
- Morpheme-side renderer changes — tracked separately in the `morpheme` repo.
- Codex-cli adapter updates — out of scope; covered by existing `docs/adapter-models.md` rationale.
- Migration of existing contract.yaml tasks — new fields are additive; old tasks keep `effort` as-is (defaults to `medium` if absent).

---

## 12. References

- `docs/plan-task-workflow-v2.md` — original Phase 1–5 plan (partly superseded)
- `docs/adapter-payload-spec.md` — current v1.1 on-wire contract
- `docs/adapter-models.md` — tier semantics + codex-cli mapping
- `src/superharness/commands/task.py:40` — current `VALID_EFFORTS`
- `src/superharness/engine/model_router.py` — current classifier
- `src/superharness/engine/orchestrator.py` — current decomposer prompt
- Session 2026-04-17 conversation — rationale trail
