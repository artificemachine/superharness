# Discussion Dispatch Fails Twice — Max Tier Ignored, Silent Failures

**Date:** 2026-05-27  
**Version:** superharness v1.67.0 (FIXED in v1.68.0)  
**Project:** nemorad  
**Status:** ✅ FIXED — tier routing + model resolution works in v1.68.0  

---

## Summary

Two discussion dispatches failed identically. The `--tier max` flag was ignored (agents dispatched at standard tier). Both agents launched but never submitted. Zero round files, zero error logs, zero retry attempts. Discussions auto-archived as `failed_participant`.

---

## Failed discussion #1

```
ID:        discuss-20260527T173607Z-48728-367842072
Topic:     "What can we add to help the learning feedback loop choose better trades?"
Command:   shux discuss start --tier max --max-rounds 3
Time:      19:38 UTC
Agents:    claude-code + opencode (gemini not included despite being available)
```

**Audit log:**
```
19:38:52  opencode    dispatched  model=deepseek-v4-flash    ← should be v4-pro (max)
19:39:02  claude-code dispatched  model=claude-sonnet-4-6    ← should be opus-4-7 (max)
```

**Result:** Both agents failed. Zero round files written. Discussion directory empty. Watcher auto-archived as `failed_participant`.

---

## Root cause analysis

### Bug 1 — `--tier max` ignored for discussion dispatch (REGRESSION)

The `--tier max` flag on `shux discuss start` is silently dropped. The `_prepare_launch_context` function in `inbox_dispatch.py` hardcodes model overrides:

```python
# Line 1488-1490
if ctx.is_discussion and ctx.item_to == "claude-code":
    model = os.environ.get("SUPERHARNESS_CLAUDE_MODEL", "claude-sonnet-4-6")
    ctx.launch_args = ctx.launch_args + ["--model", model]
```

The env var `SUPERHARNESS_CLAUDE_MODEL` is never set. The `--tier` CLI flag is never passed through to `_prepare_launch_context`. The model that gets dispatched is always the hardcoded default.

This was documented in `docs/bugs/watcher-dies-between-sessions.md` and the model tier report (`nemorad/docs/agent-model-tiers.md`). The `--tier max` flag exists on the CLI but has no code path that applies it to discussion rounds.

**This is a regression** — the `--tier` flag was added to `discuss start` but the underlying dispatch code was never updated to consume it.

### Bug 2 — Standard tier dispatches fail silently at 19:38 UTC

Both claude-code (Sonnet 4.6) and opencode (DeepSeek V4 Flash) were dispatched with short prompts (~1,300 chars) but never returned. No round files, no error logs.

| Test | Result |
|------|--------|
| Claude Haiku direct CLI test | ✅ works (instant "OK") |
| Claude Sonnet 4.6 direct CLI test | ⏳ hung (interrupted) |
| Earlier discussion (11:18 UTC) with same models | ✅ all 3 agents submitted |
| Later discussion (19:38 UTC) with same models | ❌ both failed |

The timing pattern (works at 11:18, fails at 19:38) and the Sonnet hang suggest **Anthropic API degradation** during the evening window. However, the superharness watcher provides no visibility into the agent subprocess state — no timeout log, no process tracking, no stderr capture.

### Bug 3 — Zero retry for discussion dispatch

Both inbox items went from `launched` to `failed` to `done` (auto-archived) with zero retry attempts. The retry budget (max_retries=3) was never consumed. The watcher treats discussion failures as terminal immediately, without attempting a single retry.

This was the same bug from `docs/bugs/gemini-discussion-dispatch-silent-failure.md`. The v1.68.0 orphan recovery fix only covers orphaned inbox items — it doesn't add retry logic for discussion round failures.

---

## Impact

Two discussions lost in one session. The second discussion was strategically important (learning feedback loop improvements) and would have benefited from max-tier analysis. 

Stacking impact:
- `failed_participant` counter: 1 → 2 (both from this session)
- Discussion quality degraded: forced to rely on single-agent (opencode) analysis instead of multi-agent synthesis
- Trust in `--tier max` broken: operator believes they're getting max tier but gets standard

---

## Recommended fixes (prioritized)

### 1. Wire `--tier` flag into discussion dispatch (CRITICAL) — ✅ DONE in v1.68.0

`_prepare_launch_context()` must read the tier from the discussion context and resolve it to the correct model ID for each agent. The `model_routing.py` module already has `resolve_model(owner, tier)` — it just needs to be called.

```python
# Proposed fix in _prepare_launch_context:
if ctx.is_discussion and ctx.item_to == "claude-code":
    tier = ctx.discussion_tier or "standard"  # from the discussion config
    model = resolve_model("claude-code", tier)
    ctx.launch_args = ctx.launch_args + ["--model", model]
```

Apply the same for all agents (opencode, gemini-cli).

### 2. Capture agent stderr on failure (HIGH)

When a discussion round dispatch fails, capture the last N lines of the agent subprocess's stderr and write them to the superharness log. Right now the failure is completely silent — no way to distinguish "API rate limit" from "binary crash" from "timeout."

### 3. Add retry for discussion round failures (MEDIUM)

Discussion rounds should retry at least once before marking `failed_participant`. The retry should escalate tier (mini → standard → max) to account for transient API issues.

### 4. Add dispatch heartbeat for long-running rounds (LOW)

If a discussion round dispatch has been running for > 5 minutes, emit periodic heartbeat log lines so the operator knows the agent is still working and not hung.
