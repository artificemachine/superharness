# PLAN — superharness L5: close G5c, wire dormant learning loops, prevent fleet-brain regressions

Target repo: `~/DevOpsSec/superharness`. All paths repo-relative unless stated. Source verdict and gate definitions: `docs/brain-scan-2026-07-12.md` (L4.5; blocker = G5c "loop demonstrably fired" unobserved; dormant: `rank_owners` uncalled).

## 1. Scope summary

Take superharness from L4.5 to an evidence-backed L5 and make the level durable. Built: (1) a `shux doctor` fleet health gate that actually calls the fleet endpoint and verifies the configured model exists; (2) a fix to the `shux onboard` fleet template so it stops writing `localhost` (the root cause of the six-month silent fleet death — IPv6-first resolution hitting a second server on the same port); (3) endpoint failover in `_call_fleet`; (4) quality-ranked fallback routing — `review_dao.rank_owners` (1,393 live outcome rows, zero callers today) wired into `_auto_recover_exhausted_failures_sqlite`'s fallback selection, making recorded outcomes change routing; (5) a session-scoped launchd pollution guard for the test suite; (6) a fault-injection verification harness for the reinforce loop — CI-safe e2e with the fleet mocked, plus a live script whose one real run produces the `reinforce_analysis` trace event that closes G5c; (7) vLLM per-tier fleet endpoints enablement (config + docs; code already supports it). Explicitly NOT built: `profile_trials` activation (needs an investigation spike — trial evaluation is wired, trial creation path unknown), any change to the reinforce loop's classification logic itself, and no fabricated failure data — the G5c evidence comes from a controlled fault injected through the real dispatch pipeline.

Smallest possible v1: Iteration 6 alone (the harness + one live run) closes G5c and moves the verdict; everything else is durability.

Source docs: `docs/brain-scan-2026-07-12.md`, `docs/brain-multi-agent-tiers-fleet.md`.

## 2. Prerequisites

- Live local Ollama with the configured fleet model pulled (done 2026-07-12; user fleet config now points at explicit IPv4 loopback). The live-run step of iteration 6 requires it reachable.
- Existing code touched: `src/superharness/commands/doctor.py` (fleet block at ~311-327), `src/superharness/commands/onboard.py` (`_section_fleet` at 651+, `localhost` at ~688/697/716-717), `src/superharness/engine/model_router.py` (`_call_fleet` at 215-244, `_load_fleet_config` at ~155-177), `src/superharness/commands/inbox_watch.py` (`_FALLBACK_ORDER` at 1247, `_auto_recover_exhausted_failures_sqlite` at 1443, fallback selection at 1536-1565, `_REINFORCE_WINDOW_MINUTES` at 3519, `_maybe_pause_agent` at 3524, reinforce failure-window query at 3630-3641, `_self_heal` at 3796), `src/superharness/engine/review_dao.py` (`rank_owners` at 67-105, `OwnerStats`), `tests/unit/test_launchd_test_pollution.py`.
- `pytest` harness already present (tests/unit, tests/e2e, tests/engine). No coverage `fail_under` configured in pyproject.toml — coverage deltas below are qualitative; no gate change planned.
- Risk: iteration 7 (vLLM endpoints) depends on the GPU lab boxes being reachable from this machine — external, may be tunnel-gated; iteration is config+docs and degrades to "documented, not enabled" if unreachable.
- Risk: the live-run step of iteration 6 mutates a sandbox project's state only — but the reinforce loop paths import from the INSTALLED or repo package depending on invocation; the script must run against the repo checkout (`PYTHONPATH=src`) to certify the shipped code.

## 3. Iterations

#### Iteration 1 — doctor fleet health gate

**Goal:** `shux doctor` actually calls the fleet endpoint's model-list API and verifies each configured model exists — WARN with a fix hint when the endpoint is down or a model is missing, instead of today's config-echo PASS.

**Shippable on its own?** Yes — pure doctor enhancement; would have caught both halves of the six-month fleet outage.

**Source references:**
- src/superharness/commands/doctor.py — the fleet block (~311-327) prints PASS from `_load_fleet_config()` alone, never contacting the endpoint; the new check extends this block.
- src/superharness/engine/model_router.py — `_call_fleet` (215-244) shows the endpoint shape (`{endpoint}/chat/completions`); the health check hits `{endpoint}/models` (OpenAI-compatible list) with a short timeout.
- docs/brain-scan-2026-07-12.md — the "Fleet fix applied" section documents the exact failure modes this gate must detect (endpoint serving a different store; configured model absent).

**Files touched:**
- src/superharness/engine/model_router.py (modified — new public `fleet_health(timeout: float = 3.0) -> list[tuple[str, str, str]]` returning `(tier, model, status)` where status ∈ {"ok", "endpoint-unreachable", "model-missing"})
- src/superharness/commands/doctor.py (modified — fleet block calls `fleet_health()`; any non-ok row prints `WARN fleet/<tier>: ...` with fix hint and increments `warns`)
- tests/unit/test_doctor_fleet_health.py (new)

**Commit message:**
`feat(doctor): fleet health gate — verify endpoint reachable and configured models present`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/unit/test_doctor_fleet_health.py::test_fleet_health_ok_when_model_listed` — mock urlopen returning a models payload containing the configured model → `[("all", model, "ok")]`
  - `tests/unit/test_doctor_fleet_health.py::test_fleet_health_model_missing` — models payload without the configured model → status `"model-missing"`
  - `tests/unit/test_doctor_fleet_health.py::test_fleet_health_endpoint_unreachable` — urlopen raises URLError → status `"endpoint-unreachable"`
  - `tests/unit/test_doctor_fleet_health.py::test_fleet_health_no_config_returns_empty` — `_load_fleet_config` returns None → `[]`
  - `tests/unit/test_doctor_fleet_health.py::test_doctor_warns_on_unhealthy_fleet` — run doctor's fleet block with `fleet_health` patched to return a `model-missing` row → output contains `WARN fleet/` and the warns counter increments
- GREEN (minimal implementation to pass RED):
  - `fleet_health()`: for each (tier, model, endpoint) from config, GET `{endpoint}/models`, parse `data[].id`, compare; classify per the three statuses; never raises
  - doctor block: replace unconditional PASS lines with per-tier PASS/WARN based on `fleet_health()`
- REFACTOR (cleanup planned after GREEN):
  - Extract `_fleet_models_url(endpoint)` helper shared with nothing yet — only if the URL-join logic repeats; otherwise None

**Test pyramid for this iteration:**
- Smoke: `shux doctor` runs end-to-end on this repo and exits 0 (fleet currently healthy post-fix)
- Unit: 5 tests (listed in RED), all with mocked urlopen — no network in CI
- Integration: N/A — doctor block + router function tested at their seam via the patched-function test
- State machine: N/A
- Contract: the health statuses are a 3-value contract asserted exhaustively by the unit tests
- Regression: this iteration IS the regression guard for the 2026-07-12 fleet outage class (docs/brain-scan-2026-07-12.md "Fleet fix applied"); `test_fleet_health_model_missing` is the named regression test
- Chaos: `test_fleet_health_endpoint_unreachable` (network failure injection via mocked URLError) + add timeout case in the same test file
- E2E: N/A
- Performance: 3s timeout cap asserted in the unreachable test (doctor must not hang)
- TDD Parity: 100% — one new public symbol (`fleet_health`), directly tested 4 ways
- Coverage: small positive delta on model_router.py; no fail_under configured, unchanged

**Acceptance criteria (binary):**
- [ ] `pytest tests/unit/test_doctor_fleet_health.py -q` green
- [ ] `shux doctor` on this machine prints `PASS fleet/...` naming the live model (healthy state)
- [ ] Temporarily renaming the model in a copy of the fleet config makes doctor print `WARN fleet/` (manual check, reverted)

**Estimated effort:** M

**Blocked by:** None

#### Iteration 2 — onboard fleet template: explicit IPv4 loopback

**Goal:** `shux onboard --section fleet` writes and probes `127.0.0.1`, never `localhost`, so re-running onboard cannot regress the fleet endpoint to the ambiguous name that caused the outage.

**Shippable on its own?** Yes.

**Source references:**
- src/superharness/commands/onboard.py — `_section_fleet` (651+): the Ollama probe at ~688 (`http://localhost:11434/api/tags`), the written endpoint at ~697, and the interactive prompt defaults at ~716-717 all use `localhost`; every occurrence changes to `127.0.0.1`. The probe matters as much as the written value — probing `localhost` can detect a DIFFERENT server (IPv6-bound) than the one `127.0.0.1` reaches.
- docs/brain-multi-agent-tiers-fleet.md — records why: two servers shared the port, IPv6-first resolution.

**Files touched:**
- src/superharness/commands/onboard.py (modified — all `localhost:11434` literals → `127.0.0.1:11434`; a module-level `_OLLAMA_BASE = "http://127.0.0.1:11434"` constant replaces the scattered literals)
- tests/unit/test_onboard_fleet_ipv4.py (new)

**Commit message:**
`fix(onboard): fleet section probes and writes explicit IPv4 loopback, never localhost`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/unit/test_onboard_fleet_ipv4.py::test_no_localhost_literal_in_fleet_section` — static assert: the `_section_fleet` source (inspect.getsource) contains no `localhost` substring
  - `tests/unit/test_onboard_fleet_ipv4.py::test_written_fleet_config_uses_ipv4_loopback` — run `_section_fleet` with urlopen mocked to return an Ollama tags payload and HOME pointed at tmp_path → written fleet.yaml endpoint startswith `http://127.0.0.1:11434`
  - `tests/unit/test_onboard_fleet_ipv4.py::test_probe_url_uses_ipv4_loopback` — capture the mocked urlopen's requested URL → host is `127.0.0.1`
- GREEN (minimal implementation to pass RED):
  - Introduce `_OLLAMA_BASE`, replace the four literals
- REFACTOR (cleanup planned after GREEN):
  - None

**Test pyramid for this iteration:**
- Smoke: `python -c "from superharness.commands.onboard import _section_fleet"` imports clean
- Unit: 3 tests (listed in RED)
- Integration: the written-config test exercises probe→detect→write across the function boundary with mocked network
- State machine: N/A
- Contract: the written fleet.yaml shape (`fleet.endpoints.all`, `fleet.models.*`) asserted in the written-config test
- Regression: `test_no_localhost_literal_in_fleet_section` is the named regression test for the outage's root cause — it fails if anyone reintroduces `localhost`
- Chaos: N/A — probe-failure path already falls through silently by design (existing behavior, unchanged)
- E2E: N/A
- Performance: N/A
- TDD Parity: 100% — no new public symbols; the one new module constant is asserted by the static test
- Coverage: negligible delta; no fail_under configured, unchanged

**Acceptance criteria (binary):**
- [ ] `pytest tests/unit/test_onboard_fleet_ipv4.py -q` green
- [ ] `grep -c "localhost:11434" src/superharness/commands/onboard.py` returns 0

**Estimated effort:** S

**Blocked by:** Iteration 1

#### Iteration 3 — `_call_fleet` endpoint failover

**Goal:** when the preferred fleet endpoint errors, `_call_fleet` tries the remaining configured endpoints in tier order (mini → standard → all) instead of returning None on first failure.

**Shippable on its own?** Yes — behavior-preserving when only one endpoint is configured (today's state).

**Source references:**
- src/superharness/engine/model_router.py — `_call_fleet` (215-244): current code picks ONE endpoint via `endpoints.get("mini") or endpoints.get("standard") or endpoints.get("all")` and one model the same way, then returns None on any exception. Failover = iterate the distinct (endpoint, model) candidates in that same precedence order, first success wins.

**Files touched:**
- src/superharness/engine/model_router.py (modified — `_call_fleet` iterates candidates; extract `_fleet_candidates(fleet) -> list[tuple[str, str]]` as a new module-level helper returning ordered distinct (endpoint, model) pairs)
- tests/unit/test_call_fleet_failover.py (new)

**Commit message:**
`feat(fleet): endpoint failover in _call_fleet — try all configured tiers before giving up`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/unit/test_call_fleet_failover.py::test_single_endpoint_behavior_unchanged` — config with only `all` → one candidate; mocked success returns content (guards today's behavior)
  - `tests/unit/test_call_fleet_failover.py::test_failover_to_next_endpoint_on_error` — config with `mini` and `all` endpoints; mocked urlopen raises for the mini URL, succeeds for the all URL → returns the success content and attempted both in order
  - `tests/unit/test_call_fleet_failover.py::test_all_endpoints_failing_returns_none` — every candidate raises → None, no exception escapes
  - `tests/unit/test_call_fleet_failover.py::test_candidates_deduplicated_and_ordered` — `_fleet_candidates` with mini/standard/all pointing at the same endpoint+model → single candidate; distinct ones → mini first
- GREEN (minimal implementation to pass RED):
  - `_fleet_candidates`: build ordered pairs for tiers ("mini", "standard", "all"), pairing each tier's endpoint with that tier's model (falling back to the "all" model), dedupe preserving order
  - `_call_fleet`: loop candidates, per-candidate try/except, return first success
- REFACTOR (cleanup planned after GREEN):
  - None

**Test pyramid for this iteration:**
- Smoke: existing fleet smoke — `analyze_failure` unit path with mocked single endpoint still returns a classification
- Unit: 4 tests (listed in RED)
- Integration: N/A — single module
- State machine: N/A
- Contract: candidate ordering (mini→standard→all) is the contract, asserted by `test_candidates_deduplicated_and_ordered`
- Regression: `test_single_endpoint_behavior_unchanged` guards the current production config shape against behavior change
- Chaos: the failover tests ARE failure injection (endpoint errors, total outage); timeout raise included in the all-failing test
- E2E: N/A
- Performance: N/A — per-candidate timeout already bounded at 30s by existing code, asserted not increased
- TDD Parity: 100% — one new public-ish helper (`_fleet_candidates`), directly tested
- Coverage: small positive delta; no fail_under configured, unchanged

**Acceptance criteria (binary):**
- [ ] `pytest tests/unit/test_call_fleet_failover.py -q` green
- [ ] Live check on this machine: `analyze_failure` still classifies a missing-module error as `dependency` (single-endpoint config, behavior unchanged)

**Estimated effort:** S

**Blocked by:** Iteration 2

#### Iteration 4 — quality-ranked fallback routing (`rank_owners` gets its first caller)

**Goal:** `_auto_recover_exhausted_failures_sqlite` orders surviving fallback candidates by recorded outcome quality (`review_dao.rank_owners`: fail_rate ASC, then avg_duration_s ASC) instead of the static `_FALLBACK_ORDER`, making 1,393 recorded outcomes actually change routing decisions.

**Shippable on its own?** Yes — falls back to static order when review_store has too little data.

**Source references:**
- src/superharness/commands/inbox_watch.py — fallback selection at 1536-1565: `fallback_agents` filters `_FALLBACK_ORDER` (line 1247) by not-tried + not-quota-limited + `_agent_cli_reachable`, then takes `fallback_agents[0]`. The change re-orders the FILTERED list by quality before `[0]`; the three filters stay exactly as they are.
- src/superharness/engine/review_dao.py — `rank_owners(conn, *, task_type=None, min_task_count=3)` (67-105) returns `list[OwnerStats]` best-first; owners absent from the ranking (fewer than min_task_count rows) must sort AFTER ranked ones, preserving `_FALLBACK_ORDER` relative order among themselves.
- docs/brain-scan-2026-07-12.md — "Dormant intelligence": `rank_owners` zero callers is the finding this iteration closes.

**Files touched:**
- src/superharness/commands/inbox_watch.py (modified — new module-level `_rank_fallback_agents(conn, candidates: list[str]) -> list[str]`; called between the filter and the `fallback_agents[0]` pick; wrapped in try/except returning `candidates` unchanged on any error)
- tests/unit/test_fallback_quality_ranking.py (new)

**Commit message:**
`feat(dispatch): quality-ranked fallback routing — review_store outcomes reorder fallback agents`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/unit/test_fallback_quality_ranking.py::test_low_fail_rate_agent_ranked_first` — seed review_store: gemini-cli 5 rows fail_rate 0.0, codex-cli 5 rows fail_rate 0.8 → `_rank_fallback_agents(conn, ["codex-cli", "gemini-cli"])` returns gemini first (flips static order)
  - `tests/unit/test_fallback_quality_ranking.py::test_unranked_agents_keep_static_order_after_ranked` — only gemini has ≥3 rows; candidates ["claude-code", "codex-cli", "gemini-cli"] → gemini first, then claude-code, codex-cli in original order
  - `tests/unit/test_fallback_quality_ranking.py::test_empty_review_store_preserves_input_order` — no rows → input returned unchanged
  - `tests/unit/test_fallback_quality_ranking.py::test_ranking_error_falls_back_to_input_order` — conn raising on execute → input order, no exception
  - `tests/unit/test_fallback_quality_ranking.py::test_recover_path_uses_ranked_order` — integration through `_auto_recover_exhausted_failures_sqlite`: seeded exhausted inbox row + skewed review_store + `_agent_cli_reachable` patched True → the re-enqueued row's target_agent is the quality-ranked winner, not `_FALLBACK_ORDER[0]`
- GREEN (minimal implementation to pass RED):
  - `_rank_fallback_agents`: call `review_dao.rank_owners(conn, min_task_count=3)`, build rank index, stable-sort candidates by (ranked? rank-position : len+original-index)
  - One-line insertion at the fallback site: `fallback_agents = _rank_fallback_agents(conn, fallback_agents)`
- REFACTOR (cleanup planned after GREEN):
  - None

**Test pyramid for this iteration:**
- Smoke: import + `_rank_fallback_agents(conn, [])` returns `[]`
- Unit: 4 function-level tests (first four in RED)
- Integration: `test_recover_path_uses_ranked_order` exercises the real recover path against a seeded SQLite db
- State machine: the recover path's inbox transition (failed → re-enqueued pending to new agent) is asserted inside the integration test
- Contract: N/A — no config/schema change (reads existing review_store schema)
- Regression: `test_empty_review_store_preserves_input_order` + `test_ranking_error_falls_back_to_input_order` guard the existing static-order behavior for cold-start projects
- Chaos: the conn-raising test is the failure injection; ranking must never break recovery
- E2E: N/A — covered by iteration 6's live run which exercises dispatch end to end
- Performance: N/A — one aggregate query per recover pass, bounded by review_store size
- TDD Parity: 100% — one new public symbol, tested 5 ways
- Coverage: positive delta on inbox_watch.py; no fail_under configured, unchanged

**Acceptance criteria (binary):**
- [ ] `pytest tests/unit/test_fallback_quality_ranking.py -q` green
- [ ] `grep -n "rank_owners" src/superharness/commands/inbox_watch.py` returns at least one line (the dormant function has a caller)
- [ ] Full `pytest tests/unit -q` green (no regressions in the 194 existing inbox tests)

**Estimated effort:** M

**Blocked by:** Iteration 3

#### Iteration 5 — launchd test-pollution session guard

**Goal:** the test suite fails loudly if any test leaks a real `com.superharness.*` launchd job, catching the class of pollution found live on 2026-07-12 (a `worker-proj` job pointing at a deleted pytest tmp dir).

**Shippable on its own?** Yes.

**Source references:**
- tests/unit/test_launchd_test_pollution.py — existing guard covers session-start auto-install (Bug A), crash-log wording (Bug B), silent install failure (Bug C); the new guard extends this file with a session-scoped before/after label snapshot.
- tests/unit/test_install_scripts.py — `_fake_launchd_bin` (35-47) is the fake-launchctl pattern every watcher-install test must use; the audit step checks each test in this file routes launchctl through it.

**Files touched:**
- tests/unit/test_launchd_test_pollution.py (modified — new test class `TestNoLaunchdLabelLeaks` with a fixture capturing `launchctl list` labels at module setup and asserting no new `com.superharness.` labels at teardown; skipped on non-darwin and when `launchctl` absent)
- tests/conftest.py (modified — session-scoped autouse fixture `_launchd_leak_guard` doing the same snapshot/compare for the whole suite, warn-then-fail behavior behind env `SUPERHARNESS_STRICT_LAUNCHD_GUARD=1` so CI on Linux is unaffected)

**Commit message:**
`test(pollution): session-scoped launchd label leak guard — fail on leaked com.superharness.* jobs`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/unit/test_launchd_test_pollution.py::TestNoLaunchdLabelLeaks::test_leaked_label_detected` — with the snapshot/compare helper given a fake "after" list containing one extra `com.superharness.inbox.tmpXYZ` label → helper reports the leak
  - `tests/unit/test_launchd_test_pollution.py::TestNoLaunchdLabelLeaks::test_preexisting_labels_ignored` — identical before/after including the real production label → no leak reported
  - `tests/unit/test_launchd_test_pollution.py::TestNoLaunchdLabelLeaks::test_all_watcher_install_tests_use_fake_launchctl` — static audit: every test in test_install_scripts.py whose body invokes the install script or watcher_worker either passes a PATH containing `fakebin` or mocks the service installer (source inspection; fails if a future test forgets)
- GREEN (minimal implementation to pass RED):
  - Pure helper `find_leaked_labels(before: set[str], after: set[str]) -> set[str]` filtering to the `com.superharness.` prefix; fixture wires it to real `launchctl list` output on darwin
- REFACTOR (cleanup planned after GREEN):
  - None

**Test pyramid for this iteration:**
- Smoke: full `pytest tests/unit/test_launchd_test_pollution.py -q` green on this machine with the production watcher label present (proves pre-existing labels don't false-positive)
- Unit: 3 tests (listed in RED)
- Integration: the autouse conftest fixture is exercised implicitly by every suite run
- State machine: N/A
- Contract: the `com.superharness.` prefix filter is the contract — asserted by both helper tests
- Regression: `test_leaked_label_detected` is the named regression test for the 2026-07-12 `worker-proj` leak
- Chaos: N/A — the guard itself is the failure detector
- E2E: N/A
- Performance: N/A — two `launchctl list` calls per suite run
- TDD Parity: 100% — one new helper, tested both directions
- Coverage: test-code only; no fail_under configured, unchanged

**Acceptance criteria (binary):**
- [ ] `pytest tests/unit/test_launchd_test_pollution.py -q` green
- [ ] `launchctl list | grep com.superharness | wc -l` is identical before and after a full local `pytest tests/unit -q` run
- [ ] The static audit test fails when a deliberately-broken scratch test omitting the fake launchctl is added (manual check, then removed)

**Estimated effort:** S

**Blocked by:** Iteration 4

#### Iteration 6 — reinforce-loop fault-injection harness (closes G5c)

**Goal:** a CI-safe e2e test proving the reinforce loop's full mechanics with the fleet mocked, plus `scripts/verify-l5-loop.sh` — a live-run script that injects a real ≥2-failure cluster through the actual inbox/failure path in a sandbox project and captures the resulting `reinforce_analysis` trace event with a real fleet classification: the G5c evidence.

**Shippable on its own?** Yes — the e2e test alone is a permanent regression guard on the loop; the script's one live run is the verdict-mover.

**Source references:**
- src/superharness/commands/inbox_watch.py — the reinforce failure path: window query at 3630-3641 reads `inbox WHERE status='failed' AND failed_at >= window_start` grouped by `target_agent`, requires ≥2 failures per agent (`if len(failures) < 2: continue`), calls `analyze_failure` (3662-3668), tries `_self_heal` (3673), emits `trace_event(project_dir, "reinforce_analysis", {...})` (3685-3692), pauses via `_maybe_pause_agent` (3524) only on `permanent_block`. The harness seeds exactly what this query reads: two failed inbox rows for one agent with `failed_at` inside `_REINFORCE_WINDOW_MINUTES` (30, line 3519).
- src/superharness/engine/trace.py — `trace_event` signature and the JSONL shape the assertions parse.
- src/superharness/engine/model_router.py — `analyze_failure` (279-300): the mocked boundary in the e2e test; the REAL call in the live script.
- docs/brain-scan-2026-07-12.md — G5c definition ("demonstrably fired — evidence in live data or logs"); the live run's captured event is appended here by the operator afterwards.

**Files touched:**
- tests/e2e/test_reinforce_loop_fires.py (new)
- scripts/verify-l5-loop.sh (new — bash, `set -euo pipefail`; builds a sandbox project under `mktemp -d`, seeds two failed inbox rows for `codex-cli` with a distinctive `ModuleNotFoundError`-style reason via a small inline `PYTHONPATH=src python3` snippet using inbox_dao, clears the `reinforce` cooldown row, invokes `_reinforce_loop(sandbox)` directly, then greps the sandbox's trace.jsonl for `reinforce_analysis` and prints the event)

**Commit message:**
`test(reinforce): fault-injection harness — e2e loop mechanics + live G5c verification script`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/e2e/test_reinforce_loop_fires.py::test_two_failures_trigger_analysis_event` — sandbox project, two failed inbox rows for one agent inside the window, `analyze_failure` patched to return `"dependency"` → after `_reinforce_loop`, sandbox trace.jsonl contains a `reinforce_analysis` event with `classification == "dependency"` and `failures == 2`
  - `tests/e2e/test_reinforce_loop_fires.py::test_single_failure_does_not_trigger` — one failed row → no `reinforce_analysis` event
  - `tests/e2e/test_reinforce_loop_fires.py::test_permanent_block_pauses_agent` — `analyze_failure` patched to `"permanent_block"`, `_self_heal` patched to `(False, "no heal")` → `_maybe_pause_agent` effect observable (agent pause recorded; assert on the pause side-effect the function writes)
  - `tests/e2e/test_reinforce_loop_fires.py::test_stale_failures_outside_window_ignored` — two failures with `failed_at` older than `_REINFORCE_WINDOW_MINUTES` → no event
- GREEN (minimal implementation to pass RED):
  - No production code changes expected — the tests exercise existing paths; GREEN is the harness fixtures (sandbox builder seeding `.superharness/` + SQLite via inbox_dao/init_db) plus the script
  - If RED exposes a real defect in the loop (possible — this path has never been observed firing), fix it inside this iteration and add the fix line to the commit body
- REFACTOR (cleanup planned after GREEN):
  - Extract the sandbox-project fixture to tests/e2e/conftest.py if a second e2e file wants it; otherwise None

**Test pyramid for this iteration:**
- Smoke: `bash scripts/verify-l5-loop.sh --dry-run` builds the sandbox and seeds rows without invoking the fleet, exits 0
- Unit: 2 — `test_seed_failures_creates_window_rows` (the harness's seeding helper writes exactly N failed inbox rows with in-window failed_at) and `test_read_reinforce_events_parses_trace_lines` (the event-reader helper returns only reinforce_analysis dicts from a mixed trace fixture); both in tests/e2e/test_reinforce_loop_fires.py alongside the e2e tests
- Integration: the four e2e tests each cross inbox-DB → reinforce-loop → trace-file boundaries
- State machine: `test_permanent_block_pauses_agent` covers the failed→paused agent transition; the non-transition cases (single failure, stale window) cover the guard edges
- Contract: the `reinforce_analysis` event schema (agent, failures, classification keys) asserted in the first test
- Regression: `test_single_failure_does_not_trigger` + `test_stale_failures_outside_window_ignored` pin the trigger conditions so future tuning can't silently widen them
- Chaos: the whole iteration is controlled fault injection; additionally the first test asserts no exception escapes when trace-write targets a read-only dir (sandbox variant)
- E2E: the live run of `scripts/verify-l5-loop.sh` (real fleet call, real classification) — executed once by the operator; its output block is the G5c evidence
- Performance: N/A
- TDD Parity: 100% of new helper symbols in the harness fixtures have direct use in the four tests; no production symbols added
- Coverage: positive delta on inbox_watch.py reinforce paths; no fail_under configured, unchanged

**Acceptance criteria (binary):**
- [ ] `pytest tests/e2e/test_reinforce_loop_fires.py -q` green (fleet mocked, CI-safe)
- [ ] One live `scripts/verify-l5-loop.sh` run prints a `reinforce_analysis` event whose classification is a valid taxonomy word produced by the real local fleet model
- [ ] The live event block is appended to docs/brain-scan-2026-07-12.md as the G5c closure evidence

**Estimated effort:** M

**Blocked by:** Iteration 5

#### Iteration 7 — vLLM per-tier fleet endpoints enablement

**Goal:** the GPU-lab vLLM boxes become configured per-tier fleet endpoints (config + docs), with iteration 1's doctor gate showing their live health — or, if the lab is unreachable from this machine, the enablement is fully documented and the config left commented with the reason recorded.

**Shippable on its own?** Yes — worst case ships as documentation + doctor visibility.

**Source references:**
- src/superharness/engine/model_router.py — `_load_fleet_config` (~155-177) and iteration 3's `_fleet_candidates`: per-tier `endpoints.{mini,standard,max}` already resolve; no code gap.
- docs/brain-multi-agent-tiers-fleet.md — records that vLLM speaks the same OpenAI-compatible API and that the user fleet config already sketches the per-tier block commented out.

**Files touched:**
- docs/fleet-vllm-enablement.md (new — how to enable per-tier vLLM endpoints, the reachability prerequisite, the doctor verification step, and the localhost-vs-explicit-IP lesson)
- tests/unit/test_fleet_per_tier_config.py (new)

**Commit message:**
`docs(fleet): vLLM per-tier endpoint enablement guide + per-tier config shape tests`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/unit/test_fleet_per_tier_config.py::test_per_tier_endpoints_resolve_in_candidates` — a fleet dict with distinct mini/standard endpoints+models → `_fleet_candidates` returns both, mini first (locks the per-tier contract the doc promises)
  - `tests/unit/test_fleet_per_tier_config.py::test_doctor_health_covers_all_configured_tiers` — `fleet_health` with a 2-tier config and mocked urlopen → returns one row per tier
- GREEN (minimal implementation to pass RED):
  - Expected zero production code (both behaviors land in iterations 1 and 3); these tests pin the multi-tier shape those iterations only exercised single-tier. If either fails, the gap is fixed here.
  - Write the enablement doc; update the user's fleet config out-of-repo only if the lab responds to a models-list probe
- REFACTOR (cleanup planned after GREEN):
  - None

**Test pyramid for this iteration:**
- Smoke: `shux doctor` still exits 0 with the current single-tier config
- Unit: 2 tests (listed in RED)
- Integration: N/A — network-dependent enablement is manual, gated on lab reachability
- State machine: N/A
- Contract: the per-tier fleet.yaml shape is the contract, asserted by both tests
- Regression: N/A — pure addition (doc + shape tests)
- Chaos: N/A — endpoint-failure behavior already covered by iteration 3's tests
- E2E: manual: one real classify call routed through a vLLM endpoint IF reachable; recorded in the doc's verification section either way
- Performance: N/A
- TDD Parity: 100% — no new production symbols; both doc-promised behaviors have pinning tests
- Coverage: test-only delta; no fail_under configured, unchanged

**Acceptance criteria (binary):**
- [ ] `pytest tests/unit/test_fleet_per_tier_config.py -q` green
- [ ] docs/fleet-vllm-enablement.md exists and contains the doctor verification step
- [ ] Either a vLLM endpoint answers the models-list probe and is enabled in the user fleet config, OR the doc records the unreachability finding with the probe command used

**Estimated effort:** S

**Blocked by:** Iteration 6

## 4. Test inventory summary

| Iter | Smoke | Unit | Integration | State machine | Contract | Regression | Chaos | E2E | Performance | TDD Parity | Coverage Δ |
|------|-------|------|-------------|---------------|----------|------------|-------|-----|-------------|------------|------------|
| 1    | 1     | 5    | 0           | 0             | 1        | 1          | 2     | 0   | 1           | 100%       | small +, no gate |
| 2    | 1     | 3    | 1           | 0             | 1        | 1          | 0     | 0   | 0           | 100%       | negligible |
| 3    | 1     | 4    | 0           | 0             | 1        | 1          | 2     | 0   | 0           | 100%       | small + |
| 4    | 1     | 4    | 1           | 1             | 0        | 2          | 1     | 0   | 0           | 100%       | + on inbox_watch |
| 5    | 1     | 3    | 1           | 0             | 1        | 1          | 0     | 0   | 0           | 100%       | test-only |
| 6    | 1     | 0    | 4           | 1             | 1        | 2          | 1     | 1 (live) | 0     | 100%       | + on reinforce paths |
| 7    | 1     | 2    | 0           | 0             | 2        | 0          | 0     | 1 (manual) | 0   | 100%       | test-only |

## 5. End-to-end definition of done

Deduplicated acceptance criteria:
- All seven iterations' pytest files green; full `pytest tests/unit -q` green (no regressions)
- `shux doctor` performs a live fleet health check and currently passes
- `grep -c "localhost:11434" src/superharness/commands/onboard.py` = 0
- `rank_owners` has a production caller; seeded-outcome test flips fallback order
- launchd label count identical before/after a full local unit-suite run
- One live `scripts/verify-l5-loop.sh` run captured a `reinforce_analysis` event with a real fleet classification; event appended to docs/brain-scan-2026-07-12.md
- vLLM enablement doc exists with verification steps; per-tier config shape pinned by tests

The demo script (manual E2E):
1. `shux doctor` → fleet rows show PASS with live model names
2. `bash scripts/verify-l5-loop.sh` → prints the captured `reinforce_analysis` event (real fleet classification of the injected fault)
3. Seed a skewed review_store in a scratch project, trigger recover → re-enqueue targets the quality-ranked agent
4. Re-run `/brain-scan .` → expected verdict L5 (G5c closed by step 2, G5b doubly closed by step 3)

The green command:
```
pytest tests/unit/test_doctor_fleet_health.py tests/unit/test_onboard_fleet_ipv4.py tests/unit/test_call_fleet_failover.py tests/unit/test_fallback_quality_ranking.py tests/unit/test_launchd_test_pollution.py tests/e2e/test_reinforce_loop_fires.py tests/unit/test_fleet_per_tier_config.py -q
```

## 6. Out of scope

- `profile_trials` activation (0 rows ever) — trial evaluation is watcher-wired but the creation path is unknown; needs an investigation spike before any plan is honest. Own task after this plan.
- Changes to the reinforce loop's classification taxonomy or window/threshold tuning — the harness pins current behavior; tuning is a separate decision with the harness as its safety net.
- Making `rank_owners` task_type-aware in the fallback path (per-task-type ranking) — needs task_type available at the recover site; deferred until the coarse ranking proves useful.
- Fleet API-key/auth support for remote vLLM behind auth — lab endpoints are LAN-open today; add when a secured endpoint exists.
- CI-side live-fleet tests — CI runners have no Ollama; the mocked e2e is the CI guard, the live script is operator-run by design.

## 7. Open questions

- Iteration 7: are the GPU-lab vLLM boxes currently reachable from this machine without a tunnel? The iteration ships either way, but the answer decides whether enablement is config-now or documented-for-later.
