# Steal list — omnigent → superharness (2026-07-19)

Source: read-only code study of omnigent-ai/omnigent (7.5k stars, direct
competitor: meta-harness orchestrating Claude Code/Codex/Cursor/Pi). Three
subsystem reads: harness abstraction, policy engine, state/runtime. Ranked by
leverage-for-effort **for superharness specifically** — each item maps to a
known superharness weakness from the 2026-07-19 job-ready/arch audit.

## Tier 1 — direct fixes for audited weaknesses (do these)

### 1. Harness registry + Executor protocol (kills the watcher god-module)
Omnigent: harness name → module exporting `create_app()`, all implementing one
`Executor.run_turn(...) -> AsyncIterator[ExecutorEvent]` with a small typed
event vocabulary (TextChunk, ToolCallRequest, TurnComplete, ExecutorError
(retryable: bool)) — `runtime/harnesses/__init__.py:36-148`,
`inner/executor.py:518-596`. Adding an agent = one adapter file.
**Superharness adopt:** `dispatch/harnesses/{claude,codex,gemini,opencode}.py`
implementing a `Harness` protocol + dict registry. This is the natural seam to
split the 4.5k-line `inbox_watch.py` along (audit: senior-review MAJOR).

### 2. ALLOW/DENY/ASK policy verdicts + fail-closed phase whitelist
Omnigent: policies intercept phases (request/tool_call/...), return
ALLOW|DENY|ASK; DENY short-circuits, ASKs merge into one approval; pre-execution
phases fail CLOSED when evaluation errors, post-execution fail OPEN
(`runtime/policies/engine.py:283-383`, `policies/types.py:61,202-263`).
ASK maps exactly onto superharness's human-approval philosophy.
**Adopt:** evaluator in the watcher before each dispatch; ASK → new
`awaiting_approval` status on the dashboard; one `FAIL_CLOSED_TRANSITIONS`
constant (delegate, close fail closed; hygiene checks fail open).

### 3. Dual watchdog: idle timeout + absolute ceiling (upgrade to deadline fix)
Omnigent: per-turn IDLE watchdog (240s, reset on every event) + absolute cap
(3600s) + 15s heartbeats (`_scaffold.py:80-125`). Active-but-long turns never
die; wedged ones die in 4 min.
**Adopt:** direct upgrade of the just-fixed `_check_deadlines` — track
last-event timestamp per dispatch, deadline = idle-based, ceiling = absolute.
Depends on item 4 for the event feed.

### 4. Hook recorder + transcript tailing (live progress without stdout parsing)
Omnigent's native Claude wrap: installs Claude Code hooks POSTing events out +
background forwarder tailing the transcript JSONL with **persisted byte-offset
cursors**, dedupe rings, dead-letter queue (`claude_native_forwarder.py:53-62`).
No stdout parsing, no waiting for subprocess exit.
**Adopt:** superharness already installs Claude hooks — extend to PostToolUse/
Stop events writing into SQLite; tail `~/.claude/projects/*.jsonl` by byte
offset for live per-task progress. Feeds items 3 and 5.

### 5. Snapshot + SSE live-tail with bounded queues (kills dashboard polling)
Omnigent: stateless in-process fan-out broker, no replay; clients fetch DB
snapshot then live-tail SSE, dedupe by item id; subscriber queue registered
BEFORE snapshot so the partition is exact; 1024-cap queues where overflow
drains the backlog, injects an `_OVERFLOW` sentinel, client reconnects via
snapshot (`runtime/session_stream.py:39-78,255-318`). Slow tab can never grow
server memory.
**Adopt:** ~150-line broker module; watcher publishes task transitions
(`loop.call_soon_threadsafe` makes sync-watcher → async-dashboard work);
dashboard = one snapshot read + SSE tail, never re-polls state.db.

### 6. Cost budget policy with soft-ASK checkpoints + downgrade escape hatch
Omnigent `cost_budget`: soft thresholds ASK once ("$2.50 passed, continue?") —
approval recorded via state_updates applied only on approve; hard cap DENYs
only expensive models (cheap ones keep running); unpriced models fail closed to
ASK (`builtins/cost.py:416-553`).
**Adopt:** `spend` table keyed by task/session fed from agent usage reports;
watcher asks via dashboard before dispatch when the task tree crosses a
threshold. Fits the existing tier/model-routing work (harness-02).

## Tier 2 — cheap wins, port almost verbatim

### 7. Test-environment guardrails
`check_test_environment()` hard-fails any test run whose DB isn't
in-memory/tmp/test-named before mutation (`testing/guardrails.py:1-120`).
Superharness had exactly this bug class (test state leaking into $HOME, fixed
in PR #12). ~50 lines, port verbatim into conftest.

### 8. Heartbeat-timestamp liveness (drop PID checks)
`runner_last_seen` column + pure `is_fresh(last_seen, ttl=90s)` — any reader
decides daemon liveness from the DB, no ps/PID files
(`stores/conversation_store/__init__.py:171-195`).
**Adopt:** watcher stamps a row each cycle; `shux status` + dashboard use one
helper. Fixes the "watcher stale 6023m" ambiguity (dead vs deliberately down).

### 9. Ordered live-state write chokepoint
One module, single-worker executor (ordering guarantee), dedupe dict (no row
churn), dropped-write evicts its dedupe entry so the next publish retries
(`server/session_live_state.py:1-36`). The disciplined alternative to the
blanket `except Exception: pass` pattern the audit flagged across
inbox_watch.py mirrors.

### 10. Telemetry: frozen event dataclasses + background queue emitter
One dataclass per event (created/stopped/deleted with duration/tokens/cost),
daemon-thread queue, batch flush; swallowing confined to the telemetry layer
only (`telemetry/events.py`, `telemetry/client.py`). Replaces print-based
observability (arch audit A8) without try/except pollution in business logic.

### 11. Conformance bench with drift detection
`HarnessCapabilities` declares interrupt/streaming/resume per harness; a bench
live-probes real CLIs and exits non-zero on DRIFT between declared and observed
(`harness_capabilities.py:80-136`, `tests/harness_bench/`).
**Adopt:** `shux bench` — one trivial task per configured agent CLI, diffed
against a capabilities table. Answers "does dispatch still work after Claude
Code vX ships" mechanically.

## Tier 3 — worth knowing, adopt later or partially

### 12. Labels as schema-free metadata + resume-by-label
Fork/closed/dangerous flags are all session labels — "survives reload without
a schema migration"; `resume <id>` reads the wrapper label and re-dispatches
(`stores/conversation_store/__init__.py:26-80`, `resume_dispatch.py:10-21`).
**Adopt:** `task_labels` table + `shux resume <task-id>` preloading context.

### 13. Layered context compaction (least-lossy-first)
L1 clears old tool-result bodies ("re-call tool if needed"), L2 incremental LLM
summary with `last_item_id` watermark, L3 emergency truncation; context size
LEARNED from the first overflow error, not configured (`runtime/compaction.py`).
**Adopt:** L1+L3 for `shux context <id>` assembly.

### 14. Unified RetryPolicy via env-var transport
One frozen RetryPolicy dataclass with per-SDK adapters, serialized to
`HARNESS_*_RETRY_POLICY` env vars so subprocess agents inherit the same budget
(`spec/types.py:42-224`).

### 15. Registry-as-allowlist for policy handlers
Dotted-path registry with JSON-Schema-validated factory params — the single
allowlist at every untrusted attach point, so arbitrary callables can't be
smuggled in (`policies/registry.py:31-66,156-279`). Matters the day policies
become user-configurable.

## Anti-steal (deliberately NOT copying)

- **Store abstraction layer**: 1.5k-line ABC + 3.7k-line SQLAlchemy impl to
  support SQLite AND Postgres. Superharness's plain SQLite DAO is a feature —
  simpler, auditable. Steal the patterns, not the abstraction.
- **Client-server split + WS runner tunnels, web/mobile surfaces**: different
  product. Superharness is single-operator local-first; keep it.
- **9 sandbox providers**: integration surface a solo project can't maintain.

## Suggested sequencing

1. #7 guardrails + #8 heartbeat liveness (one small PR, immediate)
2. #1 harness registry as the seam for the inbox_watch.py split (the audit's
   biggest refactor, now with a proven target shape)
3. #4 transcript tailing → #3 idle watchdog → #5 SSE dashboard (event-stream
   arc, each step consumes the previous)
4. #2 policy verdicts + #6 cost budget (the governance layer; big differentiator
   for the "auditable single-operator harness" positioning)
