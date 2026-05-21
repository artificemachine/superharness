# Plan: Hermes Self-Improvement Adaptation for Superharness

**Date:** 2026-05-20 | **Source:** Hermes agent patterns (Nous Research)
**Principle:** Extract patterns, don't copy runtime. Superharness orchestrates agents; Hermes IS an agent. Adapt the learning loops, not the execution model.

---

## What We're Building

Three self-improvement mechanisms adapted from Hermes:

| # | Feature | Hermes equivalent | Why adapt |
|---|---------|-------------------|-----------|
| 1 | **Agent-writable memory** (two-tier) | MEMORY.md | Agents learn per-session; watcher injects into dispatch |
| 2 | **Tool-loop guardrails** | Loop detection + block | Prevents budget-burning retry loops |
| 3 | **Auto-promotion** (project → global) | MEMORY.md cross-session | What project A learns, all projects benefit from |

---

## Architecture

```
~/.config/superharness/memory/           ← GLOBAL: machine-wide
  patterns.md
  pitfalls.md
  conventions.md

.superharness/memory/                    ← LOCAL: per-project
  conventions.md
  decisions.md

Watcher dispatch cycle:
  1. Load global memory files
  2. Load project memory files
  3. Inject into agent context (via engine/context_hint.py)
  4. Agent reads as mandatory context

Agent write-back:
  Agent appends to .superharness/memory/*.md during session
  Watcher reads before next dispatch

Auto-promotion:
  Pattern in project memory with ≥3 occurrences + no project-specific refs
  → promoted to global memory
```

---

## Iterations

### Iteration 1: Agent-Writable Memory Infrastructure
**Files:** `engine/agent_memory.py` (new), `engine/context_hint.py` (extend)
**Tests:** `tests/engine/test_agent_memory.py`
- RED: test_memory_files_dont_exist → fail
- GREEN: create global + per-project memory directories
- RED: test_context_hint_injects_memory → fail
- GREEN: extend build_context_hint() to inject memory content
- RED: test_agent_writes_memory → fail
- GREEN: agent appends to .superharness/memory/conventions.md

### Iteration 2: Tool-Loop Guardrails
**Files:** `commands/inbox_watch.py` (wire), `engine/loop_detector.py` (extend)
**Tests:** `tests/engine/test_loop_guard.py`
- RED: test_loop_detected_in_log → fail (no watcher wiring)
- GREEN: wire detect_loop into watcher log analyzer
- RED: test_loop_escalates_to_blocked → fail
- GREEN: escalate to blocked when loop detected, with reason
- RED: test_warn_escalation → fail (multiple cycles)
- GREEN: LoopGuard stateful escalation (warn → warn → block)

### Iteration 3: Auto-Promotion
**Files:** `engine/agent_memory.py` (extend), `commands/inbox_watch.py` (wire)
**Tests:** `tests/engine/test_memory_promotion.py`
- RED: test_pattern_not_promoted_below_threshold → fail
- GREEN: track occurrence count per pattern
- RED: test_pattern_promoted_to_global → fail
- GREEN: promote to global after ≥3 occurrences + no project refs
- RED: test_cross_project_learning → fail (project B reads project A's promotion)
- GREEN: inject global memory alongside project memory

---

## E2E / Smoke Tests
- `tests/test_smoke_memory.py`: full cycle — agent writes memory → watcher dispatches next agent → context includes memory
- `tests/test_smoke_loop_guard.py`: full cycle — agent loops → log analyzed → task blocked
- `tests/test_smoke_promotion.py`: full cycle — project A fails 3x → pattern promoted → project B's dispatch includes global memory

## Success Criteria
- [ ] Zero retry loops go undetected (watcher catches all tool loops)
- [ ] Agent-written memory is injected into next dispatch context
- [ ] Cross-project learning via promotion works end-to-end
