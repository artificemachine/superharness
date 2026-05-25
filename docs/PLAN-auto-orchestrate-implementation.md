# PLAN: Auto-Orchestrate — Implementation

**Date:** 2026-05-25
**Status:** ✅ Implemented (PR #285, #286 merged to main)

## What changes

Three patches that make the orchestrator (best model) the default dispatch path, replacing Haiku's free-tier classification.

### Patch 1 — Orchestrator prompt upgrade (`engine/orchestrator.py`)

**Before:** orchestrator only outputs subtask decomposition (list of subtasks with model_tier).

**After:** orchestrator outputs a full **routing plan**:

```json
{
  "owner": "claude-code",
  "tier": "max",
  "effort": "high",
  "decompose": false,
  "rationale": "single-file bug fix, no decomposition needed",
  "subtasks": []
}
```

Or when decomposition IS needed:

```json
{
  "decompose": true,
  "rationale": "cross-cutting feature touching 6 files",
  "subtasks": [
    {"id": "feat.st1", "title": "...", "owner": "codex-cli", "tier": "standard", "effort": "medium"},
    {"id": "feat.st2", "title": "...", "owner": "claude-code", "tier": "max", "effort": "high"},
    {"id": "feat.st3", "title": "...", "owner": "gemini-cli", "tier": "standard", "effort": "medium"}
  ]
}
```

Changes to `_ORCHESTRATOR_PROMPT`:
- Add owner selection criteria (codex for code gen, claude for reasoning, gemini for speed, opencode for budget)
- Add effort selection criteria (high for safety/design, medium for features, low for chores)
- Add `decompose` boolean to output schema
- Keep existing acceptance criteria, file count, complexity signals

### Patch 2 — Auto-orchestrate in dispatch (`commands/delegate.py`)

**Before:** orchestrator is opt-in (`--orchestrate` flag):

```python
if orchestrate and target in ("claude-code", "codex-cli"):
    orch = Orchestrator(project_dir=project_dir)
    decomposition = orch.decompose(task_data)
    ...
    # dispatch subtasks
```

**After:** orchestrator is default, opt-out (`--no-orchestrate`):

```python
# 3.5 Auto-orchestrate (default — skip with --no-orchestrate)
if not no_orchestrate:
    orch = Orchestrator(project_dir=project_dir)
    routing = orch.route(task_data)        # new method: returns RoutingPlan

    if routing.decompose:
        # Write subtasks to SQLite
        _record_decomposition(project_dir, task_id, routing)
        # Dispatch each subtask individually
        for st in routing.subtasks:
            _dispatch(project_dir, st.id, st.owner, st.tier, st.effort)
        return

    # No decomposition — apply routing plan to this task
    target = routing.owner
    resolved_model = _resolve_model(target, routing.tier)
    resolved_effort = routing.effort
```

New `--no-orchestrate` flag (not `--skip-orchestrate` — explicit opt-out, not passive skip):

```python
p.add_argument("--no-orchestrate", action="store_true", default=False,
               help="Skip orchestrator — dispatch directly (for trivial fix/chore tasks)")
```

Backward compat: `--orchestrate` flag still works (forces orchestrator, same behavior as today).

### Patch 3 — Effort-aware summary (`commands/delegate.py`)

**Before:** prints generic "Effort: medium"

**After:** prints per-owner effort meaning:

```python
def _format_effort(owner: str, effort: str) -> str:
    """Return human-readable effort description for the given owner."""
    supports = ADAPTER_REGISTRY[owner].get("supports_effort", False)
    budget = EFFORT_BUDGET_MAP.get(effort, 2.00)
    if supports:
        labels = {"low": "fast, shallow reasoning",
                  "medium": "balanced reasoning depth",
                  "high": "deep, thorough reasoning",
                  "max": "maximum reasoning (extended thinking)"}
        return f"{effort} → {labels.get(effort, effort)} (budget cap: ${budget:.2f})"
    else:
        return f"{effort} → ⚠️ {owner} doesn't support effort levels (budget cap: ${budget:.2f})"
```

Dispatch output example:

```
Orchestrator routing for feat.sqlite-sot:
  Owner:    claude-code
  Model:    claude-opus-4-7 (max)
  Effort:   high → deep, thorough reasoning (budget cap: $5.00)
  Plan:     direct dispatch (no decomposition needed)
```

With decomposition:

```
Orchestrator routing for feat.auto-dispatch:
  Decomposed into 3 subtasks:
    - st1: Implement router  [codex-cli, standard, $1.50 est]
    - st2: Write tests        [claude-code, max, $3.20 est]
    - st3: Update docs        [gemini-cli, mini, $0.40 est]
  Total estimated: $5.10
```

## Opt-out flow

```
shux delegate <id>                    → auto-orchestrate (default)
shux delegate <id> --no-orchestrate   → skip orchestrator, direct dispatch
shux delegate <id> --orchestrate      → force (backward compat)
```

## Failure handling (unchanged from existing)

1. Orchestrator tries models in chain: Opus 4.7 → Opus 4.6 → GPT-5.5 → Gemini 3.1 Pro → DeepSeek V4 Pro
2. All fail → fallback to standard dispatch (current behavior)
3. Subtask dispatch uses existing retry/failure pipeline (inbox_watch, zombie reconciler)

## Files

| File | Patch | Lines changed |
|------|-------|---------------|
| `engine/orchestrator.py` | 1: prompt upgrade + `route()` method | ~80 |
| `commands/delegate.py` | 2: auto-orchestrate default | ~60 |
| `commands/delegate.py` | 3: effort-aware summary | ~25 |
| `tests/unit/test_orchestrator.py` | Test new routing output | ~40 |
| `tests/unit/test_delegate_*.py` | Test auto-orchestrate + opt-out | ~30 |

**Total:** ~235 lines. One session, one task.
