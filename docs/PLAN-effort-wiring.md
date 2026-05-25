# PLAN: Effort Wiring — Reasoning Depth, Not Just Budget

**Date:** 2026-05-25
**Status:** ✅ Implemented — manifests updated with `supports_effort`, contract tests enforce it

## Current state

Effort is resolved by `delegate.py` (CLI → task → auto-classify → profile → fallback "medium") and passed to launchers as `--effort low/medium/high/max`. But actual reasoning control is inconsistent:

| Owner | Handles `--effort`? | What happens |
|-------|---------------------|-------------|
| claude-code | ✅ Yes | `--effort high` → `claude --effort high` (native support) |
| codex-cli | ✅ Yes | `--effort high` → `codex -c model_reasoning_effort="high"`. Maps `max` → `xhigh`. |
| gemini-cli | ❌ **No** | `--effort` silently ignored. No reasoning depth control. |
| opencode | ❌ **No** | `--effort` silently ignored. No reasoning depth control. |

Additionally, effort is **only used for budget capping** in `delegate.py`:

```
EFFORT_BUDGET_MAP = {low: $0.50, medium: $2.00, high: $5.00, max: $15.00}
```

This is a **safety net**, not a reasoning control. A user setting `--effort high` gets the same reasoning depth as `--effort low` on gemini/opencode, just with a higher spending cap.

## Actual mapping (verified from CLI --help)

| Effort | Claude | Codex | Gemini | OpenCode | Budget cap |
|--------|--------|-------|--------|----------|------------|
| low | `--effort low` ✅ | `model_reasoning_effort=low` ✅ | **unsupported** ❌ | **unsupported** ❌ | $0.50 |
| medium | `--effort medium` ✅ | `model_reasoning_effort=medium` ✅ | **unsupported** ❌ | **unsupported** ❌ | $2.00 |
| high | `--effort high` ✅ | `model_reasoning_effort=high` ✅ | **unsupported** ❌ | **unsupported** ❌ | $5.00 |
| max | (n/a) | `model_reasoning_effort=xhigh` ✅ | **unsupported** ❌ | **unsupported** ❌ | $15.00 |

Neither `gemini --help` nor `opencode run --help` expose thinking-budget or effort flags. Effort only controls reasoning depth for **Claude and Codex**. For Gemini and OpenCode, effort = budget cap only.

### 3. Adapter manifests

Add `supports_effort: true/false` to each manifest for documentation/clarity.

## UX advice

### Problem: effort is invisible to users

A user runs `shux delegate <id>` and sees `Effort: medium`. They don't know what "medium" means for their specific agent. The only visible effect is the budget cap change if they pick `high`.

### Recommendation: surface per-agent effort meaning

```
$ shux delegate <id> --effort high

  Owner:        claude-code
  Model:        claude-opus-4-7 (max)
  Effort:       high → Claude will think longer before responding
  Budget cap:   $5.00
```

Or when effort is unsupported:

```
  Effort:       high → ⚠️ opencode doesn't support effort levels
                         (budget cap raised to $5.00, reasoning depth unchanged)
```

### Recommendation: auto-effort from orchestrator

When the orchestrator is the default path, effort should be part of its output:

```json
{
  "owner": "claude-code",
  "tier": "max",
  "effort": "high",
  "rationale": "safety-critical architecture decision — needs deep reasoning"
}
```

The user shouldn't need to think about effort. The orchestrator picks it based on task shape.

### Recommendation: separate budget from effort

Budget and effort serve different purposes:
- **Effort** = reasoning depth (quality/safety lever)
- **Budget** = cost ceiling (financial safety net)

Today they're conflated. They should be independent:
- A bug fix might need `effort: high` (think hard) but `budget: $1.00` (it's one file)
- A refactor might need `effort: low` (straightforward) but `budget: $5.00` (many files)
- The orchestrator should set both independently

## Files to touch

| File | Change |
|------|--------|
| `scripts/delegate-to-gemini.sh` | Add `--effort` → `--thinking-budget` mapping |
| `scripts/delegate-to-opencode.sh` | Add `--effort` handling |
| `adapter_manifests/*.yaml` | Add `supports_effort` field |
| `commands/delegate.py` | Print per-agent effort meaning in dispatch summary |
| `engine/orchestrator.py` | Include effort in routing plan output |
