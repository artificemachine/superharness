# Brain Scan — superharness — 2026-07-12

**Verdict: L4.5 — Stateful, with one verified self-improvement loop** — run shape: installed pipx CLI (v1.77.2) + launchd background watcher (the production shape; verdict applies to it).
L4 passes on every gate with live data; L5 is half-credited: one closed learning loop (behavioral prompt adaptation) is autonomous and live-evidenced, but the headline L5 mechanisms (fleet failure-analysis→pause, outcome-based routing, A/B trials) are dormant or broken in production, and the one closed loop's final composed artifact (a dispatched prompt containing profile text) was not directly captured.

## Evidence packet

- Scanned: repo at commit `7f5bc95d` (main, v1.77.2) — identical to installed pipx copy (upgraded from PyPI today; `superharness --version` = 1.77.2). Live artifacts inspected: XDG state.db, `trace.jsonl` (190 MB), behavioral profile JSONs, live Ollama endpoint, launchd service state.

| Gate | Pass/Fail | Evidence |
|---|---|---|
| G1 live LLM invocation | PASS | dispatch shells out to `claude`/`codex`/`gemini` CLIs (delegate.py prompt assembly at 1094–1140 feeding launcher scripts); local Ollama HTTP call `model_router.py:215-240` |
| G2a ≥2 models/tiers | PASS | `MODEL_MAP` 3 agents × mini/standard/max tiers, model_router.py:17-29 |
| G2b selection executes | PASS | availability-aware fallback `_agent_cli_reachable` wired into `_auto_recover_exhausted_failures_sqlite` filter (shipped v1.77.0, PR #34); quota-aware exclusion alongside it; fleet classify returns (tier, effort) model_router.py:253-259 |
| G3a autonomous loop | PASS | launchd `com.superharness.inbox.superharness` loaded (doctor PASS today), one-shot tick per ~15s; auto_enqueue_todo / auto_peer_approve / auto_retry / auto_recover in `_run_scripts` |
| G3b output drives dispatch | PASS | agent CLI output → handoffs/status → auto-close/auto-advance; ledger 3,997 rows of watcher-driven actions |
| G3c retry/escalation fires | PASS | retry with max_retries + fallback-agent rerouting + escalate-to-operator; 150 rows in `failures` table = the paths have run |
| G4a persistent state | PASS | XDG state.db: tasks 10,258 rows, handoffs, ledger, operator_memory 71, review_store 1,393, watcher_cooldowns 13 |
| G4b state read back | PASS | `build_context_hint` (context_hint.py:90-130) injects agent memory + behavioral profile + failure-pattern remediation into every dispatch prompt (delegate.py:1094, 1106-1140); watcher_cooldowns read every tick (v1.77.1) |
| G4c artifact non-empty | PASS | row counts above; behavioral profile JSONs freshly written today with real distributions |
| G5a outcomes recorded | PASS | `review_dao.record` per dispatch (inbox_dispatch.py:~480-490): owner, task_type, score, failed — 1,393 live rows |
| G5b outcomes change decision | PASS (one loop) | behavioral profiles extracted FROM recorded outcomes (behavioral.py:98-235, reads tasks + review_store) → formatted into dispatch prompt (context_hint.py:104-115 → delegate.py:1094). "Different prompt" per gate definition |
| G5c loop demonstrably fired | PARTIAL | extraction side: watcher refreshes every 10 cycles (inbox_watch.py:2307-2315), profile files updated today 08:14 UTC with sample_count up to 10,258, confidence "high" — observed. Injection side: unconditional in the dispatch path, dispatches demonstrably run — but no captured dispatched prompt containing profile text |

**Strongest case FOR:** the behavioral loop is fully closed in code and autonomous: dispatch outcomes → review_store/tasks (live rows) → watcher-scheduled `refresh_behavioral_profile` (observed firing today, timestamps) → `format_profile_for_context` → every dispatch prompt. No human in that loop anywhere.

**Strongest case AGAINST (checked, and what stuck):**
- The fleet failure-analysis→pause loop (the most "self-improving"-looking code, inbox_watch.py:3660-3700 + model_router.analyze_failure) is **broken in production**: fleet config names a local model that is NOT present in the live Ollama instance (four other models are), so `_call_fleet` fails → classification always "unknown" → `_maybe_pause_agent` never fires via this path. Zero `reinforce_analysis`/`reinforce_self_heal`/`reinforce_agent_pause` events in 190 MB of trace.jsonl. This refutation stuck — that loop gets no credit.
- `rank_owners` (outcome-quality → owner routing, review_dao.py:67) has **zero callers** — outcome data never changes routing. Stuck.
- `profile_trials` (A/B trial system): 0 rows — never used. Stuck.
- These three refutations are why the verdict is L4.5, not L5.

**Not checked:** dashboard/UI LLM surfaces; MCP server paths (`shux mcp`); Windows service run shape; whether `format_profile_for_context` output is non-empty for the exact current profile contents (assumed from code + populated fields); the discussion/consensus multi-agent subsystem's live behavior.

**What would change the verdict:** capture one real dispatched prompt containing the behavioral-profile block (→ full L5 on the existing loop), OR fix the fleet model reference and observe one `reinforce_analysis` event with a resulting pause/heal (→ L5 via the failure loop), OR wire `rank_owners` into owner selection (→ L5 via routing).

## Brains inventory

| Brain | Tier | Runs | Invoked from | Live? |
|---|---|---|---|---|
| claude CLI (Anthropic frontier/mid per tier map) | mini→max | cloud | delegate.py dispatch → launcher scripts | LIVE |
| codex CLI (gpt-5.x per MODEL_MAP model_router.py:22-24) | mini→max | cloud | same dispatch path | LIVE |
| gemini CLI (gemini-2.5-* model_router.py:27-29) | mini→max | cloud | same dispatch path | LIVE |
| Ollama local model via fleet endpoint (model_router.py:215-240) | local small | local | classify_effort + analyze_failure | **BROKEN** — configured model absent from live Ollama |
| Peer-review agents (cross-agent max-tier, `_PEER_AGENTS` inbox_watch.py) | max | cloud | auto_peer_approve_plans | LIVE |

## Dimension findings

- **Routing (2):** 3-agent × 3-tier map; availability-aware (`shutil.which`) + quota-aware fallback filter in exhausted-retry recovery; fleet-based (tier, effort) classification with agent-CLI fallback chain (model_router.py:253+, `_try_classify`).
- **Agency (3):** launchd one-shot watcher respawned by operator; six auto-mode lifecycle rules; peer-approval dispatches a *different* max-tier agent to judge plans — multi-agent verification without a human.
- **Memory (4):** four read-back streams into dispatch prompts: agent memory, behavioral profile, failure-pattern remediation (failure_patterns.py:391), context files. Plus watcher_cooldowns/state read every tick.
- **Learning (5):** one closed loop live (behavioral), three dormant/broken (fleet-pause, rank_owners, profile_trials).
- **Cognition engineering (6):** peer-review verdict prompts (`_PEER_REVIEW_PROMPT` inbox_watch.py), plan_validator + report_verifier quality gates, effort tiers stamped per task.

## Dormant intelligence

- Fleet failure-analysis → self-heal/pause loop: fully built, broken by a one-line config/model mismatch. Highest-value fix in this report.
- `rank_owners` outcome-quality routing: built, never called.
- `profile_trials` A/B behavioral trials: schema + evaluate loop wired into watcher (inbox_watch.py:2313), zero trials ever created.
- Secondary GPU-fleet endpoints: commented out in fleet config.

## What one level up would take

Smallest legitimate move to L5: pull the configured fleet model in Ollama (or point fleet config at a model that exists there) — the failure-analysis loop then runs on the next watcher tick with ≥2 same-agent failures in the window, and one observed `reinforce_analysis` → pause/heal event closes G5c outright. One config change plus one observed event.

## Correction (same day, post-scan)

The brains inventory above is incomplete: **opencode is a 4th live agent brain**, missed by a truncated grep. Evidence: `MODEL_MAP["opencode"]` model_router.py:31-35 (deepseek tiers); 3rd in the classifier chain (`opencode run -m {model}`, line 208); primary reasoner equal to claude in `_DISCUSSION_TIER_ROUTING` (lines 650-667, gemini/codex capped at standard while claude/opencode get max). Verdict unaffected (adds another LIVE row to the inventory; no gate changes). Full detail: `docs/brain-multi-agent-tiers-fleet.md`.

## Fleet fix applied (same day, post-scan)

The "BROKEN" fleet row is now FIXED, and the root cause was deeper than the scan concluded. Not just a missing model: **two different Ollama servers shared port 11434** — native Ollama bound `127.0.0.1` (IPv4 only) while a container-platform VM bound `*:11434` including IPv6. The fleet endpoint said `localhost`, which resolves `::1` first → every fleet call for months hit the container VM's *separate* Ollama with its own model store. Even the model list the scan inspected was the wrong instance's.

Fix: pulled `qwen2.5:7b` into native Ollama + pinned the fleet endpoint to explicit `127.0.0.1`. Verified end-to-end, real inference: `analyze_failure` classifies a missing-module error as `dependency` (correct); `_classify_via_fleet` routes a trivial README task to `(mini, low)` and a twice-failed cross-system migration to `(max, high)` (correct discrimination). G5b now fully live; **G5c closes when the first `reinforce_analysis` event lands in trace.jsonl** — requires a real ≥2-failure cluster in a reinforce window, deliberately not forced. Re-scan then; expected verdict: L5.


## Re-scan (same day, 09:47 UTC)

Delta re-scan after the fleet fix. G1-G4c unchanged (only fleet config + docs changed since the morning scan). Findings:

- **Reinforce loop confirmed live in production**: watcher_cooldowns shows `reinforce` last ran 09:45:27 UTC (~90s before the re-scan), all 13 auto-actions ticking with fresh timestamps — which also live-verifies the v1.77.1 cooldown-persistence fix end to end.
- **G5c still unobserved, for the honest reason**: zero failures recorded today (failures table + failed inbox rows both 0 since 09:00), so the fleet analyze step has had no ≥2-failure cluster to fire on. The loop is armed and scheduled; the triggering condition simply has not occurred since the fix landed. Not fabricating one.
- **Verdict unchanged: L4.5** — but G5b is now stronger than at scan time (fleet verified with real inference, loop scheduling observed live, only the final firing event outstanding).
- Housekeeping: found and removed a leaked launchd watcher job pointing at a deleted pytest tmp dir (`worker-proj`, exit 1) — pollution from a pre-rewrite test variant that ran the real install script during a full-suite run. The rewritten test fakes launchctl; pollution class already has a guard test file, worth extending to this label pattern.

Next re-scan trigger: first `reinforce_analysis` event in trace.jsonl → close G5c → L5.
