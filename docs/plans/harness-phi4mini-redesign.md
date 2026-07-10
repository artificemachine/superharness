# phi4-mini/Ollama Harness — Redesign Against Current Main

## Status

Re-derived design. Supersedes the old, unmerged `celstnblacc/superharness#134`
("feat(harness): phi4-mini harness layer — self-healing watcher +
availability-first orchestrator", base v1.34.3). That PR is **not being
ported** — its base is ~40 versions behind current main and a large fraction
of what it proposed already exists in different form. This doc re-derives
the goal against current architecture instead of adapting old code.

Old PR reference (celstnblacc fork, dead): `docs/plans/harness-layer-phi4mini.md`
at commit `354f674a477cf4c6926e380882dfc788bd8dbd55`. Read for context only.

## Goal (unchanged from the original proposal)

1. **Self-healing watcher** — richer health decisions than "did the process
   exit" (restart / break_lock / escalate / continue).
2. **Availability-aware dispatch** — route tasks to whichever agent owner is
   actually reachable right now, with failover after repeated failures,
   without task-content assumptions about agent skill.

## Why this needs a redesign, not a port

Three systems the old PR proposed building from scratch already exist on
current main, evolved independently over ~40 versions:

### 1. Watcher self-healing already exists — `engine/operator.py`

`Operator.monitor_and_recover()` (`operator.py:288-389`) is a live poll loop
(default 5s) that already does crash-detect → respawn → circuit-break:
- Distinguishes clean watcher exits (rc=0, expected every tick) from crashes.
- Circuit breaker: `_max_restarts=5` within `_restart_window=600s`
  (`operator.py:41-44`), trips and cools down 600s on repeated crash-loop.
- Full process-group kill on restart to avoid orphans (`_kill_process`,
  `operator.py:391-443`).
- `check_watcher_health()` reads heartbeat staleness (`stale_threshold_sec=120`,
  `operator.py:491-519`); `check_resource_conflicts()` covers stale inbox locks
  (`operator.py:534-546`).

This is real, working, and battle-tested (this exact process was live and
correctly restarted with a fresh PID during tonight's session). It is
coarse-grained — binary alive/respawn, no distinction between "hung mid-cycle"
and "crashed," no `break_lock`/`escalate` decision tree — but a new advisor
must sit **above** this, feeding richer signals into decisions the existing
loop doesn't make. It must not reimplement respawn/circuit-breaking.

### 2. A local-model advisor mechanism already exists — the "fleet" path

`model_router.py:149-323` ("fleet" concept) reads
`~/.config/superharness/fleet.yaml`, calls a self-hosted OpenAI-compatible
HTTP endpoint (`_call_fleet`, `model_router.py:215-244`, documented as "local
GPU VMs superharness itself uses for internal AI operations"), and is
consumed by two things:
- `_classify_via_fleet()` — task tier/effort classification.
- `analyze_failure()` (`model_router.py:263-303`) — agent-failure root-cause
  classification (transient/permanent_block/config/dependency/timeout/unknown),
  consumed by `_reinforce_loop()`/`_maybe_pause_agent()` in `inbox_watch.py`
  to auto-pause an agent the fleet classifies as permanently blocked.

This is architecturally the same idea as "phi4-mini advises watcher/dispatch
decisions" — a self-hosted model, not task-content-aware, feeding operational
decisions. **This is the single biggest duplication risk in the old PR.**

### 3. ReviewStore already exists — `engine/review_dao.py` + `review_store` table

Schema (`db.py:331-341`), DAO (`review_dao.py`), and a real consumer already
exist: `behavioral.py` uses `review_store` for the A/B profile-trial
verification loop (the same system touched in tonight's PR #28 —
`complete_trial()`'s revert path). The old PR's Iteration 6 `ReviewStore`
(record owner/task_type/duration/score/failed, query stats) is functionally
identical to what's already shipped and in active use.

### 4. Dispatch failover already exists, but reactively — `inbox_watch.py`

There is no `_resolve_owner`-style function in `inbox_dispatch.py` — owner is
decided at enqueue time, and dispatch just claims whatever `target_agent` was
set. Retry/failover logic lives in `inbox_watch.py` instead:
- `_auto_fallback_owner_reassign()` (`inbox_watch.py:1393-1505`) — reassigns
  retry-exhausted tasks to a single statically configured
  `profile.yaml: auto_fallback_owner`.
- `_auto_recover_exhausted_failures_sqlite()` (`inbox_watch.py:1508+`) — for
  exhausted-retry failures, classifies via `failure_classifier.classify()`
  and picks the next untried agent from a hardcoded rotation
  `_FALLBACK_ORDER = ["claude-code", "codex-cli", "gemini-cli", "opencode"]`
  (`inbox_watch.py:1333`), filtered by `is_agent_quota_limited()` and by
  agents already tried on that task.

This is real but **reactive only** (fires after retry exhaustion) and **not
availability-aware** (only signal is "quota-limited" or "already tried," never
a live reachability check). Genuine gap: nothing checks agent availability
*before* or *at* initial routing time. But any new mechanism must feed into
`_FALLBACK_ORDER` / `_auto_fallback_owner_reassign`, not run a second,
parallel reassignment path fighting over the same inbox row's `target_agent`.

### 5. Failure classification already exists, twice

`failure_classifier.classify()` (regex-based, pure function, no side effects)
feeds `_auto_recover_exhausted_failures_sqlite()`'s retry-vs-give-up and
fallback-agent decisions. `model_router.analyze_failure()` (fleet-based)
separately feeds agent-pause decisions. A third (phi4-mini) classifier needs a
clearly non-overlapping role, or it's redundant with two systems that already
do this.

## Update (same day): item A is already done

Checked `~/.config/superharness/fleet.yaml` directly rather than leaving this
as an open question. It already reads:

```yaml
fleet:
  # Primary: local Ollama (always available, no network dependency).
  # Used for: failure analysis, self-healing classification.
  endpoints:
    all: "http://localhost:11434/v1"
  models:
    all: "qwen2.5:7b"
```

Local Ollama is **already the primary fleet backend**, already wired to
`_call_fleet()`/`analyze_failure()`, already used for exactly "failure
analysis, self-healing classification" per its own comment. Item A (below)
is not a build task — it's a one-line model swap in an existing config file
if `phi4-mini` is preferred over `qwen2.5:7b`, nothing else.

This also weakens item B's case: if fleet-backed "self-healing
classification" already exists and feeds `_maybe_pause_agent()`, whoever
scopes real work here first needs to read what `_reinforce_loop()` actually
does with that classification today, before assuming a `WatcherHealthAdvisor`
gap exists at all. Not confirmed either way in this pass — flagged for
whoever picks up watcher-side work, not assumed.

## Redesigned scope

Given the above, the actual deliverable is **integration, not new modules**,
and most of it turns out to already exist:

### A. phi4-mini/Ollama as a fleet backend — already done

No work. Fleet already runs local Ollama. Swap `models.yaml`'s `qwen2.5:7b`
to `phi4-mini` only if there's a concrete reason to prefer it — not required
to unblock anything else here.

### B. WatcherHealthAdvisor — likely mostly covered, not confirmed

`operator.py` owns crash-detect/respawn/circuit-breaking (confirmed, stays
out of scope). Fleet-backed failure classification already exists and feeds
`_maybe_pause_agent()` (confirmed existence, consumption not audited in this
pass). Whether `break_lock`/`escalate` verdicts specifically are missing from
that existing path is genuinely unknown — not scoping speculative new code
without reading `_reinforce_loop()`/`_maybe_pause_agent()` first.

### C. Availability-aware pre-dispatch check — the one confirmed real gap

Everything else in the original proposal is either done (item A) or unaudited
(item B). This is the one piece with a concrete, confirmed gap: nothing
checks live CLI reachability *before* initial routing — only after retry
exhaustion, and only via "quota-limited"/"already-tried" flags, never a real
reachability probe. Must integrate with `_auto_fallback_owner_reassign()` /
`_FALLBACK_ORDER` (`inbox_watch.py:1333`), not add a second reassignment path
racing over the same inbox row's `target_agent`.

### D. ReviewStore — reuse existing, do not rebuild

Any new harness outcome-tracking needs go through `review_dao.py` /
`review_store`. No new table, no new module.

### E. Failure classification — do not add a third classifier

Two classification paths already exist (`failure_classifier.classify()`,
fleet-backed `analyze_failure()`). Nothing here needs a third.

## Explicitly out of scope (from the old PR, dropped)

- `harness/config.py`, `harness/model_client.py`, `harness/fallback.py`,
  `harness/review_store.py` — superseded by fleet.yaml (already live) +
  review_dao.py (already live).
- `install-launchd-ollama.sh` — fleet already runs against local Ollama with
  no launchd wiring beyond whatever the user already has `ollama serve`
  running under. Not needed.
- Iteration 11's `advise_failover()` as a standalone function — folds into
  item C's integration with `_auto_fallback_owner_reassign()`.
- Item B (`WatcherHealthAdvisor`) as new code — deferred pending an audit of
  what the existing fleet-backed classification path already covers.

## Revised subtask mapping

- `harness-01-design-doc` — this document. Done.
- `harness-02-dispatch-availability` — item C, the one confirmed real gap:
  live CLI reachability check feeding `_FALLBACK_ORDER` /
  `_auto_fallback_owner_reassign()`. No Ollama/fleet dependency.
- Everything else from the original 5-subtask plan (owner-registry-as-fleet-
  config, watcher-advisor, launchd-install) is either already done (item A)
  or not yet justified by evidence (item B) — not carrying forward as
  separate tracked tasks. If item B turns out to have a real gap after
  auditing `_reinforce_loop()`/`_maybe_pause_agent()`, scope it fresh then
  rather than resurrecting the old plan's assumptions.
