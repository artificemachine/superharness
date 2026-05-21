# Auto-Mode Gap Analysis

> Date: 2026-04-27
> Author: investigation across one debugging session on `fix/operator-nonblocking-dashboard-card-ui`
> Scope: identify what's structurally missing from superharness "auto mode" so the operator only has to approve plans and close reports.

## Premise

The promise of auto mode is a simple operator contract:

1. **Approve plans** the system thinks need human judgment.
2. **Close reports** that verification couldn't auto-resolve.

Everything else (dispatch, retry, recovery, lifecycle transitions, store consistency) should run without operator input. This document captures every place that promise currently breaks, grouped by structural cause.

## Operator role: ideal vs. actual

| Activity | Ideal | Actual |
|---|---|---|
| Approve plans | yes/no on plans flagged as needing judgment | yes/no, plus you read the full handoff (no quality gate) |
| Close reports | yes/no on reports that passed verification | yes/no, plus you often run `shux close` manually because `auto_close` is gated by `tests_passed` which most handoffs forget to set |
| Manage stuck tasks | none | manual archive of stale `in_progress`, `review_requested`, orphaned subtasks, ghost inbox items |
| Restart watcher/dashboard | none | rare, but happens (zombie processes, port conflicts) |
| Reconcile YAML/SQLite drift | none | recurring (every bug we hit on 2026-04-27 traced back here) |

## Bugs found in one session (2026-04-26 to 2026-04-27)

For context, the four structural gaps below were derived from these concrete failures:

1. `delegate-to-claude.sh` line 86 crashed on bash 3.2 with `set -u` and an empty `CLAUDE_ARGS` array. Silent failure: dispatch marked items as launched, then nothing happened.
2. macOS `script -q -F` returned exit code 0 when its child crashed abnormally. Combined with #1, the dispatcher saw "success" and left items in `launched` until the 20-minute zombie reconciler caught them.
3. Six orphaned subtasks of an archived parent task kept getting auto-enqueued every watcher cycle, because the YAML had no status on them and the YAML→SQLite sync defaulted them to `todo`.
4. Discussions cancelled via the dashboard left their contract task stuck at `in_progress` forever (no sync from `state.yaml` to contract).
5. `mock.alpha` sat at `report_ready` for days because `_auto_close_report_ready` required `tests_passed: true` and the handoff never set it.
6. `mock.beta` sat at `review_requested` indefinitely because no code path times out a stalled review.
7. Dashboard auth token regenerated on every restart, breaking open browser tabs with cryptic "forbidden" errors.
8. Timer column was empty for pending and paused items because the dashboard only used `launched_at`, not `created_at`.
9. SQLite said `pending`, YAML said `paused` for the same item. The dashboard showed `pending`. The watcher saw `paused`. Both were "right" relative to their own store.
10. `os.kill(pid, 0)` returned True for zombie processes, so the watcher monitor thought a dead watcher was still alive.
11. Browser opened a new tab every 5 seconds because `launchd KeepAlive` plus a forking CLI plus a new monitor PID each cycle equaled a tight restart loop.
12. Manually paused items (with `reason` set) were being auto-retried out of pause because the retry loop didn't respect the manual intent.

Every one of these was the user doing operator work the system should have done.

## The four structural gaps

### 1. Dual-store inconsistency is the single biggest source of bugs

Every "ghost" we chased traced back to YAML and SQLite disagreeing.

- `contract.yaml` and `tasks` SQLite table.
- `inbox.yaml` and `inbox` SQLite table.
- `discussions/*/state.yaml` and `discussions` SQLite table.
- `handoffs/*.yaml` (no SQLite mirror).
- Profile (`profile.yaml`, no mirror).

The `yaml_sync_queue` tries to keep them aligned but the relationship is lossy and direction-ambiguous. Direct SQLite writes get silently overwritten by queued YAML upserts. Direct YAML edits are seen by some readers and not others.

**Concrete examples from this session:**

- I ran `UPDATE tasks SET status='archived'` directly. The watcher's next tick drained `yaml_sync_queue`, picked up an `upsert_task` payload from the YAML import, and reverted the change.
- The dashboard read SQLite (`pending`) while the watcher read YAML (`paused`). Both were internally consistent. Together they were a bug.
- Tasks have a `state_reader.get_tasks()` indirection that auto-selects backend per `STATE_BACKEND` (default `dual`), but writers don't always go through it.

**Why it produces silent bugs:** every reader has a different effective truth. Users see one thing, the system acts on another. Manual fixes feel like they worked until the next cycle.

**Real fix:** pick SQLite as authoritative. YAML becomes export-only, regenerated on commit/snapshot. The "dual" backend is a leaky abstraction that should be retired. Migration path:

1. Make all writers go through `state_reader`/`state_writer` modules.
2. Remove direct YAML writes from the watcher and dispatcher.
3. Keep YAML generation as a `shux export` command and a post-commit hook for diff-friendliness.
4. Switch `STATE_BACKEND` default to `sqlite_only`.

### 2. No global lifecycle invariant. Every state needs a guaranteed exit

Today's lifecycle exits are case-by-case. We patched three holes in this session (`paused`, `review_requested`, `discussion in_progress`). Each was a separate reconciler. There's no system-wide rule. The full state map and current exit coverage:

| State | Exit mechanism | Status |
|---|---|---|
| `todo` | `auto_enqueue_todo` enqueues for planning | ok |
| `plan_proposed` | `auto_approve_plans` or operator | ok, but no quality gate (see gap 4) |
| `plan_approved` | `auto_enqueue_approved` enqueues for execution | ok |
| `in_progress` | none at task level | **gap** |
| `report_ready` | `auto_close` (now without `tests_passed` requirement) or operator | ok |
| `review_requested` | 120m timeout reverts to `report_ready` | new in this session |
| `paused` | 30m timeout to `failed` (skips items with manual `reason`) | new in this session |
| `failed` | `auto_retry` (skips manual reasons) or archive at max_retries | ok |
| `discussion in_progress` | reconciler archives when discussion `state.yaml` is terminal | new in this session |
| `archived` / `done` | terminal, no exit needed | ok |

**The remaining gap:** `in_progress` has no task-level timeout. A crashed agent that left its inbox item alive but produced no handoff would hang forever. The 20-minute zombie reconciler covers the inbox side but not the contract task side. If the zombie reconciler marks the inbox item `failed`, the contract task stays `in_progress`. They drift again.

**Real fix:** declare exits in a single rule table:

```python
LIFECYCLE_EXITS = {
    "in_progress":      (timeout=180, action="archive_with_reason"),
    "plan_proposed":    (timeout=24*60, action="escalate_to_operator"),
    "report_ready":     (timeout=4*60, action="escalate_to_operator"),
    "review_requested": (timeout=120, action="revert_to_report_ready"),
    "paused":           (timeout=30, action="fail_with_reason"),
    # ...
}
```

A single `_reconcile_lifecycle()` reads the rules and acts. Adding a new state means adding a row, not writing a new reconciler. The four reconcilers we have today collapse into one.

### 3. Failure attribution is silent

Every dispatch failure ends up with `failed_reason: "launcher exited with code 1"`. That message is useless for the operator and useless for `auto_retry`.

**What this session showed:**

- Two cascading silent failures (bash 3.2 unbound variable plus macOS `script` returning 0) produced exactly this message. The launcher logs had the real error (`CLAUDE_ARGS[@]: unbound variable`) but nothing surfaced it.
- The `failure_patterns` module records error snippets but doesn't classify them.
- Without classification, `auto_retry` burns retries on hopeless tasks (the 6 orphaned subtasks would have retried forever) or gives up too early on transient failures.

**What auto mode needs:**

A failure classifier that distinguishes:

- **Permanent block**: bash syntax error, missing dependency, missing contract task. Don't retry. Mark and surface.
- **Transient**: network blip, agent rate limit. Retry with backoff.
- **Quota**: out of tokens, hit budget. Surface to operator.
- **Agent crash**: agent itself exited badly. Retry once, then surface.
- **No-op**: agent ran but produced no artifact. Likely a prompt or context bug. Surface.

The dispatcher already has access to `task_log`, `launcher_rc`, `error_snippet`, and the failure_patterns history. A simple regex+heuristic classifier is enough; full LLM classification is overkill.

**Surfacing:** the dashboard should show error class plus the last 20 lines of `task_log` directly, not require operator to find launcher-logs/ on disk.

### 4. The two human-in-the-loop gates have no quality filter

This is the actual auto-mode value proposition, and it's missing.

Auto mode succeeds when:

- It only asks the operator to approve **plans worth approving** (passed structural checks).
- It only asks the operator to close **reports worth closing** (passed verification).

Today neither has a quality filter:

- `auto_approve_plans: true` blindly approves every plan. That defeats the purpose because bad plans get executed.
- `auto_approve_plans: false` blocks every plan. The operator reads handoffs and decides.
- `auto_close: true` (now without the `tests_passed` requirement) blindly closes every `report_ready` task.

**The missing middle ground:** auto-handle the easy cases, escalate the rest. Concrete heuristics that could be checked:

**Plan quality gate (block auto-approve if any fail):**

- Plan has a `tdd:` block with `red`, `green`, `refactor` keys (required by CLAUDE.md, often missing).
- Plan addresses every acceptance criterion in the contract task.
- Plan touches under N files, or declares why it touches more.
- Plan has a `risks:` section with at least one entry.
- Plan does not contain TODO markers or placeholders.

If all pass, auto-approve. If any fail, queue for operator with the failing reason highlighted.

**Report verification gate (block auto-close if any fail):**

- `tests_passed: true` is set (warn if missing, but don't block when `auto_close: true` is explicit).
- `outcome:` is non-empty and over N words.
- `context:` field exists (used by the next session to verify).
- The work referenced (`pr_url`, files mentioned) actually exists.
- No suspiciously short reports ("done" with no detail).
- Tests in the project pass (run `pytest tests/ -q` if present, gate on result).

If all pass, auto-close. If any fail, queue for operator with the failing reason highlighted.

This is what cuts the operator's workload from "every task" to "the hard ones".

## What's actually missing, in priority order

| # | Missing | Impact |
|---|---|---|
| 1 | Single source of truth (SQLite-only) | Eliminates ~80% of stale-state bugs. Highest leverage. |
| 2 | Lifecycle state machine with declared timeouts | Replaces the four reconcilers we wrote with one rule table. |
| 3 | Failure classifier (bash crash, agent crash, timeout, permanent block) | Makes `auto_retry` actually correct. Makes the dashboard useful for triage. |
| 4 | Plan quality gate before queuing for operator | Cuts approval load to only plans that need a human. |
| 5 | Report verification gate before queuing for close | Cuts close load to reports where verification was inconclusive. |
| 6 | Peer review timeout plus escalation chain | `review_requested` has a timeout now; needs an escalation path back to a human (or another peer) instead of just reverting. |
| 7 | `in_progress` task-level timeout (not just inbox-level) | Catches hung agents that wrote nothing back. |
| 8 | Structured error surface in dashboard | Operator currently tails `launcher-logs/`. Should be a panel showing error class plus last 20 lines. |

Items 1, 2, 3 are load-bearing. The rest depend on them.

## Recommended sequencing

### Phase 1 (foundation, 1-2 weeks)

- **gap-1 SQLite as source of truth.** Migrate writers, retire `STATE_BACKEND=dual`, add `shux export` for YAML snapshots.
- **gap-2 Unified lifecycle reconciler.** Replace `_reconcile_paused_*`, `_reconcile_zombies`, `_reconcile_discussion_contract`, `_reconcile_stale_review_requested` with one `_reconcile_lifecycle` driven by a rule table.
- **gap-3 Failure classifier.** New module `engine/failure_classifier.py`. Used by the dispatcher to set `failure_class` on every failed item. Used by `auto_retry` to decide retry vs. surface.

### Phase 2 (gates, 1 week)

- **gap-4 Plan quality gate.** New `engine/plan_validator.py` with the heuristics above. Wire into `auto_approve_plans`.
- **gap-5 Report verification gate.** New `engine/report_verifier.py`. Wire into `auto_close_report_ready`.

### Phase 3 (polish, ongoing)

- **gap-6 Peer review escalation.** Already partially wired (`peer_reviewers` config). Add escalation timeout per reviewer.
- **gap-7 `in_progress` task timeout.** Add to lifecycle rules (Phase 1 prerequisite).
- **gap-8 Dashboard error surface.** New panel that shows the last 5 failed items with error class plus log tail.

## What a "fully auto" session looks like

When all 8 items ship, a typical operator session is:

```
$ shux status
project: ...
inbox: pending=0 launched=2 running=0 paused=0 done=14 failed=1 stale=0
auto-handled (24h): plans approved=11, reports closed=8, tasks archived=3
needs-attention: 2

needs-attention:
  feat.foo (plan_proposed): plan missing tdd.refactor block
  fix.bar (report_ready): tests fail, see /tmp/.../bar-report.log
```

Two items, both with a clear reason. The other 22 transitions happened without operator input. That's the bar.

## Anti-goals (what auto mode should NOT do)

- Auto mode should **not** silently approve bad plans.
- Auto mode should **not** silently close failed reports.
- Auto mode should **not** retry hopeless tasks indefinitely.
- Auto mode should **not** require operators to read raw launcher logs to understand failures.
- Auto mode should **not** require operators to choose between "block on every plan" or "rubber-stamp every plan".

The current system fails on every one of these. The 8-item plan addresses each.

## References

- `src/superharness/commands/inbox_watch.py` (current reconciler implementations)
- `src/superharness/engine/state_reader.py` (dual-store backend selector)
- `src/superharness/commands/inbox_dispatch.py` (dispatch path, where failure attribution is lost)
- `.superharness/profile.yaml` (auto-mode flags: `auto_dispatch`, `auto_close`, `auto_retry`, `auto_approve_plans`, `paused_timeout_minutes`, `review_timeout_minutes`)
- Session debugging notes: this analysis was derived from a single session that hit 12 distinct bugs, all of which were variants of these 4 structural gaps.
