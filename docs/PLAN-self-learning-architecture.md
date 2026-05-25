# PLAN: Superharness Self-Learning Architecture

**Date:** 2026-05-25
**Status:** proposal

## Problem

superharness orchestrates agents but doesn't learn from outcomes. Discussions identify problems but don't create tasks. Failures repeat with no pattern recognition. The watcher reacts to symptoms, not root causes.

## Three layers

### Layer 1 — Self-HEALTH (what's alive?)

| Capability | Today | Gap | Fix |
|-----------|-------|-----|-----|
| Per-agent health | Watcher heartbeat only | No success rate, no latency tracking, no failure pattern | `agent_health` table: uptime %, avg completion time, failure rate by task type. Route away from unhealthy agents |
| Retry with context | Creates new rows, loses reason, `retry_count=0` forever | ✅ Fixed 2026-05-25 (`_retry_agent` preserves row + retry_count) | — |
| Alerting | Dashboard shows status | No push notifications on stuck tasks | Fire `shux notify` when `waiting_input > 30min`, `failed` spike, watcher down |

### Layer 2 — Self-LEARN (what works?)

| Capability | Today | Gap | Fix |
|-----------|-------|-----|-----|
| Orchestrator scoring | Quality scores per model (decompose success rate) | Only tracks decompose, not task completion | Extend to track: `task_completed` (did model finish?), `retries_used`, `classification_match` (did tier match complexity?) |
| Failure patterns | Static classifier (`failure_classifier.py`) | Doesn't learn new signatures | Persistent `failure_patterns` table. After 3 identical failures, auto-classify with category + remediation |
| Behavioral profile | Tracks `model_tier` preference per project | Doesn't track per-task-type success | `task_type_success` table: for `fix` tasks, which owner+tier succeeds most? `feat`? `discuss`? Feed back into orchestrator routing |
| Preflight | Warns on >6 criteria, stale deps | No auto-action | Auto-orchestrate when criteria > 3 (✅ fixed today), auto-escalate tier when previously failed |

### Layer 3 — Self-IMPROVE (what gets better?)

| Capability | Today | Gap | Fix |
|-----------|-------|-----|-----|
| Discussion → task pipeline | Discussions end, nothing happens | No feedback loop | After consensus, extract action items → auto-create tasks with owner+tier from orchestrator |
| Auto-remediation | `shux hygiene` finds orphans, duplicates | Doesn't auto-fix | Extend `--fix`: auto-close stale discussions, auto-archive dead tasks, auto-merge duplicate inbox items, auto-escalate stuck tasks |
| Learning rate | Orchestrator scores reset on restart | No persistence | Persist scores to SQLite (`orchestrator_scores` table). Survive restarts. |
| Cross-project learning | Per-project behavioral profiles | No global knowledge transfer | Global `failure_patterns` and `task_type_success` tables shared across projects in `~/.config/superharness/` |

## Biggest single win

**Discussion → task feedback loop.** The discussion you just started ("review production readiness") should produce findings. Those findings should become tasks with correct owner+tier assignments. The orchestrator should learn from those outcomes and route better next time.

Currently: discussion → consensus → nothing.
Should be: discussion → consensus → extract action items → auto-create tasks → orchestrator routes → agents execute → outcomes feed back into scoring.

## Implementation order

1. **Discussion → task extraction** (2h) — highest impact, closes the biggest gap
2. **Health scoring per agent** (1h) — prevents routing to broken agents
3. **Orchestrator scoring persistence** (30min) — scores survive restart
4. **Failure pattern learning** (1h) — auto-classify recurring failures
5. **Alerting integration** (30min) — notify on stuck tasks
