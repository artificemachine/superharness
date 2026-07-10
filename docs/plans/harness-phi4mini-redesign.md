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

## Redesigned scope

Given the above, the actual deliverable is **integration, not new modules**:

### A. phi4-mini/Ollama as a fleet backend option, not a parallel system

Extend `fleet.yaml` config to support a local Ollama endpoint
(`http://localhost:11434`) as one more fleet backend alongside remote GPU VMs.
Reuses `_call_fleet()`'s existing HTTP-call plumbing — no new HTTP client
module. `HarnessConfig`/`OllamaHarnessClient` from the old PR are **not
needed**; this is a fleet.yaml entry plus (if response-shape differs)
provider branching inside `_call_fleet()`.

Open question for whoever picks up `harness-02`: does Ollama's `/api/chat`
response shape match the existing OpenAI-compatible assumption closely enough
to reuse `_call_fleet()` directly, or does it need a thin adapter? Check
before writing code.

### B. WatcherHealthAdvisor — a decision layer above `operator.py`, not a replacement

New, narrow scope: given signals `operator.py` doesn't currently synthesize
(heartbeat staleness *trend* not just threshold, lock age, GC backlog size,
repeated non-zero-exit reason patterns from recent cycles), produce a
richer verdict than binary alive/respawn — specifically `break_lock` and
`escalate` actions `monitor_and_recover()` doesn't have today. Falls back to
rule-based (mirroring the old PR's `RuleBasedFallback` intent) when the fleet
backend is unreachable — never blocks the watcher cycle.

Explicitly NOT in scope: crash detection, process respawn, circuit-breaking —
`operator.py` owns those and works.

### C. Availability-aware pre-dispatch check — feeds `_FALLBACK_ORDER`, doesn't replace it

New: a lightweight `OwnerRegistry`-equivalent that checks live CLI
reachability (not just quota-limited/already-tried) *before* initial routing,
not only after retry exhaustion. Output should modify which agent gets
`target_agent` at enqueue/reassignment time — integrating with
`_auto_fallback_owner_reassign()` and `_FALLBACK_ORDER`, not adding a second
reassignment mechanism that can race with it.

### D. ReviewStore — reuse existing, do not rebuild

Any new harness outcome-tracking needs go through `review_dao.py` /
`review_store`. No new table, no new module.

### E. Failure classification — do not add a third classifier

If phi4-mini offers anything here, it should be a second opinion scoped
narrowly to cases `failure_classifier.classify()` returns `unknown` for —
not a parallel classification of every failure.

## Explicitly out of scope (from the old PR, dropped)

- `harness/config.py`, `harness/model_client.py`, `harness/fallback.py`,
  `harness/review_store.py` — superseded by fleet.yaml + review_dao.py.
- `install-launchd-ollama.sh` — only needed once fleet.yaml's local-endpoint
  support (item A) is real and someone actually wants Ollama specifically
  vs. any other fleet backend. Not blocking for the advisor logic itself.
- Iteration 11's `advise_failover()` as a standalone function — folds into
  item C's integration with `_auto_fallback_owner_reassign()`.

## Revised subtask mapping

- `harness-01-design-doc` — this document. Done.
- `harness-02-owner-registry` → becomes: fleet.yaml local-endpoint support
  (item A) + live-reachability `OwnerRegistry` (item C's registry half, no
  Ollama dependency required for the reachability-check part).
- `harness-03-watcher-advisor` → item B, built on top of fleet backend from
  harness-02.
- `harness-04-dispatch-failover` → item C's integration into
  `_auto_fallback_owner_reassign()`/`_FALLBACK_ORDER`, built on harness-02.
- `harness-05-launchd-install` → only if item A's Ollama-specific setup is
  still wanted after harness-02 lands; otherwise this subtask may be dropped
  entirely (any fleet backend already has its own setup story).

## Open decision for the operator

Before `harness-02` starts: confirm whether local Ollama/phi4-mini is still
the preferred backend, given the fleet mechanism already supports arbitrary
OpenAI-compatible endpoints (remote GPU VMs are already in use per
`model_router.py:133-137`'s own comment). If an existing fleet GPU node
already runs an OpenAI-compatible model, items B and C may need zero new
backend work — only the advisor logic itself.
