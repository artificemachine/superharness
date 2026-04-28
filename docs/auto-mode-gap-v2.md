# Auto-Mode Gap Analysis v2

> Updated: 2026-04-28 (after YAML→SQLite migration on `feature/deepseek_improvement`)
> Original: 2026-04-27 (`docs/auto-mode-gap.md`)

## What was resolved today

| Gap | Status | Notes |
|-----|--------|-------|
| 1. SQLite as source of truth | ✅ DONE | All reads/writes go to SQLite. YAML is export-only via `shux export-yaml`. |
| 2. Unified lifecycle reconciler | ✅ DONE | `lifecycle_rules.py` with `LIFECYCLE_RULES` table. Inbox + contract timeouts. |
| 3. Failure classifier | ✅ DONE | `failure_classifier.py` with 6 categories. Used by watcher for retry decisions. |
| 4. Plan quality gate | ✅ DONE | `plan_validator.py`. Blocks auto-approve on missing TDD, TODOs, no risks. |
| 5. Report verification gate | ✅ DONE | `report_verifier.py`. Blocks auto-close on missing outcome, broken PR, no files. |
| 6. Peer review escalation | ✅ DONE | `review_escalation.py` with chain. Escalated to operator after chain exhausted. |
| 7. In-progress task timeout | ✅ DONE | 180m timeout in lifecycle_rules. |
| 8. Dashboard error surface | ✅ DONE | Recent failures panel with color-coded pills and launcher log tails. |

**Additional fixes today:**
- Cross-agent orchestrator with quality-weighted random selection (Claude → Codex → Gemini)
- Exhausted failure recovery with agent fallback chains
- Escalation root cause classification (infra bug vs implementation fail)
- `stopped` items no longer block `max_concurrent_tasks` gate
- Auto-dispatch writes directly to SQLite (not YAML)
- `shux status` reads from SQLite (not YAML)
- `_yaml_writes_enabled()` always returns False

## Remaining gaps

### Gap A: Peer approval for plan_proposed tasks (NEW)

**Problem:** `plan_proposed` tasks wait for operator approval. The auto-approve hook exists but only fires during manual `shux task status plan_approved` transitions, not during the watcher cycle.

**Desired behavior:** When a task reaches `plan_proposed`, a **different agent** (at max tier) reviews the plan and approves or rejects it. This prevents the same agent from rubber-stamping its own plan.

```
claude-code proposes plan → gemini-cli (max/ultra) reviews → approves/rejects
codex-cli proposes plan  → claude-code (max/opus) reviews  → approves/rejects
gemini-cli proposes plan → codex-cli (max/gpt-5.4) reviews  → approves/rejects
```

**Implementation:**
- New watcher function: `_auto_peer_approve_plans()`
- For each `plan_proposed` task, find a peer reviewer (max-tier, different owner)
- Dispatch the plan to the peer with a review prompt
- If approved → transition to `plan_approved` and auto-enqueue
- If rejected → revert to `todo` with feedback from reviewer
- If peer fails → fallback to operator (status unchanged, surfaced)

**Design principle:** Never auto-approve without a second opinion. The reviewer must be a **different** agent and at **max** tier (uses orchestrator-quality models for judgment).

### Gap B: No "stale task" garbage collector

Old tasks in `in_progress`, `review_requested`, `report_ready` without handoffs sit forever. The lifecycle reconciler handles timeouts but:
- `in_progress` with no handoff → no way to auto-close/fail
- `report_ready` with no handoff → auto-close skips it
- `review_requested` with no reviewers configured → stays forever

**Fix:** Add lifecycle rules for tasks with no handoff after N hours:
```
in_progress + no handoff + > 4h → archive (agent produced nothing)
report_ready + no handoff + > 2h → archive (no report was written)
```

### Gap C: Dashboard "review mode"

The dashboard shows everything mixed. Operator needs:
- **Auto-handled** tab: tasks completed automatically (green, with report summary)
- **Needs review** tab: tasks in `report_ready`, `review_requested`, `waiting_input`
- **In progress** tab: tasks being worked on
- **Escalated** tab: `waiting_input` (infra bugs), `blocked` tasks

### Gap D: Dashboard JSON serialization

The dashboard API returns malformed JSON (keys unquoted, values showing type hints). The `_json` method uses `json.dumps()` but something in the pipeline produces invalid output. This breaks the live stream and API consumers.

### Gap E: Auto-approve not wired into watcher cycle

`auto_approve_plans` exists as a profile flag but is only checked during manual `shux task status` transitions. The watcher should also run it during its cycle — alongside `auto_enqueue_todo` and `auto_enqueue_approved`.

**Combined with Gap A:** Instead of blindly auto-approving based on `auto_approve_plans: true`, use peer review. The `auto_approve_plans` flag should mean "use peer approval" when set, not "blindly approve."

## New operator contract (after all gaps closed)

```
$ shux status
project: ...
inbox: pending=2 launched=1 running=0 done=14 failed=0
auto-handled (24h): plans peer-approved=5 reports closed=11 tasks recovered=3
needs-attention: 1

needs-attention:
  feat.foo (plan_proposed → rejected by gemini-cli): plan missing risks section
```

**The operator only touches tasks that genuinely need human judgment.** Everything else flows through:

```
todo → auto-enqueue → plan_proposed → peer-review (different agent, max tier)
    → plan_approved → auto-enqueue → in_progress → report_ready
    → auto-verify → auto-close (if tests pass) OR needs-review (if not)
    → done

Stale states: in_progress(180m) → archive, review_requested(120m) → escalate
Failed items: auto-recover (2 retries, 3 agents) → escalate/plan_proposed
```

## Implementation order

| Priority | Gap | Effort |
|----------|-----|--------|
| 1 | Gap A — Peer approval for plans | 2-3 sessions |
| 2 | Gap E — Wire auto-approve into watcher | 1 session |
| 3 | Gap B — Stale task garbage collector | 1 session |
| 4 | Gap C — Dashboard review mode | 2 sessions |
| 5 | Gap D — Dashboard JSON fix | 1 session |
