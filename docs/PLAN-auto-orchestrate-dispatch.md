# PLAN: Auto-Orchestrate Dispatch

**Date:** 2026-05-25
**Status:** proposal (not started)

## Problem

Today, when a task or discussion is created, the tier selection chain is:

```
1. --model flag (CLI)
2. task.model_tier field
3. Haiku auto-classify (runs `claude --model haiku` — cheapest model decides)
4. profile.yaml default_model
5. fallback → standard / medium
```

The orchestrator (Opus 4.7 / GPT-5.5 / Gemini 3.1 Pro / DeepSeek V4 Pro) is **opt-in** via `--orchestrate`. Without it, tasks go straight to mid-tier models with no decomposition analysis.

Two documented failures from this design:

1. **Participant floor:** Agent met the minimum (2 of 4) instead of including all
2. **Tier floor:** Haiku cheap-routes safety-critical discussions to standard tier

## Proposal

One orchestrator call per task/discussion. The best available model decides three things:

```
shux delegate <id>    (no flags needed)
        │
        ▼
   orchestrator (best model from pool)
   Opus 4.7 / GPT-5.5 / Gemini 3.1 Pro / DeepSeek V4 Pro
        │
        └─ output: routing plan
           {
             "owner": "claude-code",        // WHO
             "tier": "max",                 // WHAT TIER
             "effort": "high",              // EFFORT LEVEL
             "decompose": true,             // SPLIT?
             "subtasks": [...]              // if decompose
           }
```

**Cost:** one max-tier call = $0.02-0.05. Cheaper than a standard-tier model on a task it can't complete.

## Orchestrator decisions

### 1. WHO (owner selection)

The orchestrator picks the best agent for the task shape:

| Task shape | Preferred owner | Reason |
|-----------|----------------|--------|
| Deep reasoning, architecture | claude-code (Opus) | Best reasoning, 1M context |
| Heavy code generation | codex-cli (GPT-5.5) | Strongest code output |
| Fast turnaround, large context | gemini-cli (3.1 Pro) | Fast, 1M+ context |
| Budget-constrained | opencode (V4 Pro) | Cheapest max-tier |
| Discussion / multi-agent | All available | Cross-model consensus |

### 2. TIER

| Complexity signal | Tier |
|------------------|------|
| > 6 acceptance criteria | max |
| Design / architecture / safety | max |
| New feature (feat) | standard or max |
| Bug fix (fix) | standard |
| Chore / docs / test | mini or standard |
| Previously failed | escalate tier |

### 3. SPLIT (decomposition)

The orchestrator decides whether to decompose:

| Signal | Action |
|--------|--------|
| > 3 acceptance criteria | Decompose |
| Cross-cutting (multiple files/modules) | Decompose |
| Single-file fix, no integration | Direct dispatch |
| Discussion | Multi-agent rounds (no subtask split) |

### 4. EFFORT

Effort controls reasoning depth (supported by Claude, Codex, Gemini):

| Context | Effort |
|---------|--------|
| Architecture, safety, hard bugs | high |
| Feature implementation | medium |
| Chore, refactor, docs | low |

Not all owners support effort levels. The orchestrator assigns effort where the owner supports it.

## Failure handling

The orchestrator selects the best available model from its pool. If the chosen model fails:

```
orchestrator pool (shuffled, weighted by success rate):
  claude-opus-4-7     ──→ try first
  claude-opus-4-6     ──→ fallback (same agent, older model)
  gpt-5.5             ──→ cross-agent fallback
  gemini-3.1-pro      ──→ cross-agent fallback
  deepseek-v4-pro     ──→ last resort
```

**Failure modes:**

| Failure | Next step |
|---------|-----------|
| Rate limited (429) | Next model in chain |
| Timeout (30s) | Next model in chain |
| Invalid output (unparseable JSON) | Retry same model once, then next |
| All models fail | Fall back to standard dispatch (current behavior) |
| Chosen model unavailable at dispatch time | Existing retry/failure mechanisms (inbox_watch, zombie reconciler) |

After the routing plan is produced, each subtask is dispatched independently through the existing inbox pipeline. If a subtask's assigned owner is rate-limited at dispatch time, the standard retry/failure cycle handles it.

## Opt-out

```
shux delegate <id> --no-orchestrate   → skip orchestrator, direct dispatch
shux delegate <id>                    → auto-orchestrate (default)
shux delegate <id> --orchestrate      → force (explicit, backward compat)
```

`--no-orchestrate` is intended for trivial tasks (single-line fix, known pattern).

## Changes needed

| File | Change |
|------|--------|
| `commands/delegate.py` | Make orchestrator the default path (step between task resolution and dispatch) |
| `engine/orchestrator.py` | Extend decomposition output to include owner + tier + effort per subtask; add routing-plan-only mode (no subtask split) |
| `adapter_manifests/*.yaml` | Add `supports_effort: true/false` field |
| `tests/` | Test auto-orchestrate path, opt-out path, all-models-fail path |

## Open questions

1. **Discussion routing:** Should discussions always use all available agents (current `n-1` rule) or let the orchestrator decide the participant set?
2. **Budget cap:** Should there be a max orchestrator cost per task (e.g., $0.10)?
3. **Caching:** If the same task is re-dispatched (retry), should the orchestrator re-run? Probably yes if previously failed, no if just re-queued.
