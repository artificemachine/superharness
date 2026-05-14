# Handoff — superharness

> Latest: 2026-05-14, gateway Phase 1 + ntfy.sh backend shipped (v1.58.4 → v1.58.5)
> Previous: 2026-05-12, t-c46124 (I6 gateway listener)
> PyPI latest: v1.58.5

---

## 2026-05-14 session: gateway notifications Phase 1 + ntfy.sh backend

### What landed

| PR | Version | What |
|----|---------|------|
| #242 | v1.58.2 | Gateway relay backend — SSH exec to self-hosted relay, machine-level credentials |
| #244 | v1.58.4 | Dual backend — relay + direct Telegram bot; security audit doc |
| #246 | v1.58.5 | ntfy.sh as third direct backend; Phase 3 roadmap |

### Architecture

Outbound-only (Phase 1). GatewayListener exists but is not wired — no inbound commands.

**Dispatch priority:** relay → telegram → ntfy

All credentials at `~/.config/superharness/credentials.env` (0600). Nothing in `.superharness/`.

Credential keys: `SUPERHARNESS_RELAY_SSH_HOST`, `SUPERHARNESS_RELAY_TOKEN`, `SUPERHARNESS_RELAY_DEST`, `SUPERHARNESS_TELEGRAM_BOT_TOKEN`, `SUPERHARNESS_TELEGRAM_CHAT_ID`, `SUPERHARNESS_NTFY_TOPIC`, `SUPERHARNESS_NTFY_SERVER`.

Configure: `shux onboard --section gateway`.

### Security

Full threat model in `docs/gateway-security.md`. Relay is categorically most secure (your infra, SSH transport, no third party). ntfy.sh self-hosted is best relay-free fallback.

Phase 2 (inbound `/approve`) deferred — 5 hardening controls required: forward-origin reject, per-sender rate limit, freshness window, inline-button confirm, DM-only default.

### Phase 3 roadmap (docs/gateway-security.md)

B (next): Slack webhook as additional backend. Phase 2: inbound with hardening. C: pairing-code flow. A: inline-button approvals. D: smart digest.

### Also fixed

- `shux onboard` full wizard now invokes `ONBOARD_SECTIONS` (previously defined but never called)
- Stop-hook `session-turn-end.sh not found` — `pipx install -e .` (editable) breaks hook paths; fix: `pipx install . --force`

### Files changed

- `src/superharness/engine/relay_client.py` — relay + telegram + ntfy backends, `dispatch_notification`
- `src/superharness/ui/sections/gateway.py` — 3-backend wizard, `setup_ntfy`, `_configure_ntfy`
- `src/superharness/commands/notify.py` — uses `dispatch_notification`
- `src/superharness/commands/onboard.py` — ONBOARD_SECTIONS wired into full wizard
- `tests/unit/test_gateway_wizard.py` — 35 tests
- `docs/gateway-security.md` — threat model, hermes comparison, Phase 1/2/3 roadmap

### Next session

1. Phase 2: 5 hardening controls (test names pre-defined in `docs/gateway-security.md`)
2. Slack webhook direct backend (~20 lines, same pattern as ntfy) if needed
3. ntfy self-hosted: configure via `shux onboard --section gateway` when server is ready

---

## 2026-05-12 session: I6 — Telegram gateway listener (t-c46124)

### What was built

`src/superharness/modules/gateway/telegram_gateway.py` — the gateway listener for I6:

- `GatewayListener(token, allowed_senders, project_dir)` — long-poll Telegram Bot API
- `parse_command(text) -> ParsedCommand | None` — parses `/approve|reject|close|reset <task_id>`, strips `@botname` suffix, case-insensitive; returns None on unknown command or missing task_id
- `validate_sender(sender_id, allowed_senders)` — allowlist check; unknown senders rejected before any DB write
- `handle_update(update)` — full pipeline: sender check → dedup via `idempotency_key` (= Telegram message_id) → parse → DB insert → execute → reply
- Returns `"unknown_sender"` / `"duplicate"` / `"help"` / `"ok:<command>"` strings (testable without HTTP)
- `HELP_TEXT` reply sent for malformed/unknown commands and commands missing task_id

`src/superharness/engine/operator_commands_dao.py` — DAO for the `operator_commands` table:
- `insert()` — INSERT OR UNIQUE constraint; returns `(row, is_new)` for dedup
- `get_by_key()`, `is_duplicate()`, `update_status()`

`src/superharness/engine/db.py` — v15 migration:
- `operator_commands` table: `idempotency_key UNIQUE`, `command`, `task_id`, `sender_id`, `status`, `result`, `created_at`, `executed_at`

### Tests

`tests/unit/test_telegram_gateway.py` — 23 tests, all pass:
- AC-1: unknown sender rejected, no row written
- AC-2: message_id deduplicates redelivery (single row after two deliveries)
- AC-3: malformed command returns "help", `_send_reply` called with HELP_TEXT
- AC-4: `parse_command` covers approve/reject/close/reset + edge cases

### Next task

`t-6af284` — I7: Gateway wizard section + shux approve/reject CLI (status: `plan_proposed`)

---

## 2026-05-11 session (latest): dashboard cards + token usage + insights

### What landed

Two iterations that close the previous deferred list: a UI surface for observations and citations on the dashboard, plus token-usage capture from HTTP providers feeding a new `shux insights` section.

| Iter | Surface | Files | Tests |
|------|---------|-------|-------|
| 10 | `#observationsCard` + `#citationCard` + Observations button on task-report card; linkified citations | `scripts/dashboard.html` | 8 markup-presence |
| 11 | Token extraction from Anthropic/Gemini/OpenAI/OpenRouter responses; `shux insights summarizer` section | `engine/summarizer_providers.py`, `engine/summarizer.py`, `engine/insights.py`, `commands/insights.py` | 12 |

20 new unit tests, all GREEN. No new external deps. CLI providers (opencode, claude-code) record NULL token columns since stdout has no token data; operators who want spend visibility must temporarily switch to an HTTP provider.

### Dashboard UX (iter 10)

The flow:

1. Operator opens a task report (existing surface).
2. Clicks the new "Observations" button on that card's header.
3. `#observationsCard` opens below and shows one card per snapshot, with phase + created_at + summary text.
4. Citation tokens in the summary (`observation/42`, `handoff/17`, `decision/8`, `failure/3`) are auto-detected and rendered as clickable links.
5. Clicking a link opens `#citationCard` and displays the full row JSON.

HTML is escaped before regex linkification, so injected anchors are safe. The markup-presence test catches accidental ID removal in future edits.

### Token usage flow (iter 11)

After this iteration, each successful HTTP-provider call:

1. Provider extracts `input_tokens` / `output_tokens` from the response shape and stores them on `self.last_usage` along with the model name.
2. `_SQLiteRateLimitedSummarizer` reads `last_usage` after the inner returns and passes the numbers into `summarizer_calls.record_call`.
3. `shux insights` rolls up per-provider call counts and token totals into a new `── summarizer ──` section.

CLI providers (opencode, claude-code) do not populate `last_usage`, so their rows have NULL token columns. The insights row still shows their call count.

### Example output

```
── summarizer ─────────────────────────
  anthropic      calls=42  ok=41  fail=1  in=8400 out=2100
  opencode       calls=130 ok=130 fail=0  tokens=n/a
```

### Files changed this commit

- `docs/PLAN-claude-mem-integration.md` (iter 10 and iter 11 sections appended)
- `src/superharness/scripts/dashboard.html` (cards + JS)
- `src/superharness/engine/summarizer_providers.py` (last_usage on three HTTP providers)
- `src/superharness/engine/summarizer.py` (_log threads model/tokens)
- `src/superharness/engine/insights.py` (_summarizer_breakdown helper)
- `src/superharness/commands/insights.py` (── summarizer ── section)
- `tests/unit/test_dashboard_observation_card_markup.py` (new)
- `tests/unit/test_summarizer_token_usage.py` (new)
- `tests/unit/test_insights_summarizer_section.py` (new)
- `HANDOFF.md` (this section)
- `CHANGELOG.md` (two appended lines)

### What's left

The previous-session deferred list is largely closed. Remaining items, all genuinely optional now:

- `shux observation list <task-id>` CLI mirror of the per-task observation route. Add when terminal-driven inspection becomes a felt need.
- `~/.superharness/.env` loader so provider/summarizer env vars persist per-project without shell rc plumbing. Useful if you onboard another machine to the same setup.
- Per-model cost rate table for converting tokens to dollars in `shux insights`. Out of scope unless you decide to track spend.
- Cross-process rate limiting backed by SQLite — already done in iter 8.

### Recommended next move

Ship the branch. Six commits sit local; iter 10 + iter 11 add roughly 1100 lines and close the deferred list. Open the PR, merge, set `SUPERHARNESS_SUMMARIZER=opencode` in your shell, and let real usage tell you what (if anything) needs more work.

```bash
gh pr create --base main \
  --title "feat: claude-mem integration (iters 1-11)" \
  --body "$(cat HANDOFF.md | head -200)"
```

### Branch state

On `docs/claude-mem-integration`, seven commits ahead of main once this commits: docs-only, iter 1-4, iter 5-6 plus canon, iter 7, iter 8, iter 9, iter 10+11. Not pushed.

---

## 2026-05-11 session (latest): claude-code summarizer

### What landed

`ClaudeCodeSummarizer` subprocesses the local `claude` CLI. Reuses whatever authentication Claude Code is configured with: Claude Max OAuth, or `ANTHROPIC_API_KEY` if you have one set. Operator gets Claude-quality summaries without putting a separate API key in env.

OpenCode and ClaudeCode now share a `_CLISummarizer` base class. The refactor is behaviour-preserving; existing OpenCode tests stay GREEN.

| Surface | Files | Tests |
|---------|-------|-------|
| `_CLISummarizer` base + `ClaudeCodeSummarizer` + registry entry | `engine/summarizer_providers.py` | 10 new (plus regression on OpenCode) |
| claude-code smoke entry | `tests/integration/test_summarizer_smoke.py` | 1 (gated) |

### Usage

```bash
# Cheap: uses DeepSeek via opencode (your existing setup)
export SUPERHARNESS_SUMMARIZER=opencode

# Claude quality via Max plan OAuth, no extra billing
export SUPERHARNESS_SUMMARIZER=claude-code
```

Set per-shell, per-project (in a `direnv` file), or globally in your shell rc. The auto-capture loop reads the env on every transition; no restart needed.

### Why both

You said you have:

- A DeepSeek API key wired through OpenCode (already works → `opencode` summarizer)
- A Claude Max plan subscription (consumer OAuth, no separate API key → `claude-code` summarizer subprocesses `claude` and inherits that auth)
- Monthly plans for ChatGPT / Gemini (consumer products, no API access; their `openai` / `gemini` summarizers require separate API keys from their developer consoles, which you do not have today)

So your usable real-provider paths today: `opencode` (DeepSeek), `claude-code` (Claude Max), `noop` (free always). The HTTP providers stay registered for future use if you ever provision keys, but you do not need them.

Recommended: start with `opencode` (Option B). Switch to `claude-code` when you want Claude-quality summaries on your Max plan. No code change; just flip the env var.

### Files changed this commit

- `docs/PLAN-claude-mem-integration.md` (iteration 9 section appended)
- `src/superharness/engine/summarizer_providers.py` (`_CLISummarizer` base, ClaudeCodeSummarizer, registry entry)
- `tests/unit/test_claude_code_summarizer.py` (new)
- `tests/integration/test_summarizer_smoke.py` (claude-code smoke entry)
- `HANDOFF.md` (this section)
- `CHANGELOG.md` (appended)

### What the next session should do

Pick from the previous deferred list, all still open:

- Token usage extraction from HTTP provider responses (Anthropic `usage.input_tokens`, OpenAI-compatible `usage.prompt_tokens`, Gemini `usageMetadata`). CLI providers (`opencode`, `claude-code`) cannot extract tokens from stdout; that is a known limitation.
- `shux insights` extension for per-provider call counts (then spend, once tokens flow).
- HTML rendering on task pages: observation cards + clickable `decision/42`-style citations using the iter-8 JSON routes.
- `shux observation list <task-id>` CLI mirror of the per-task route.
- `~/.superharness/.env` loader so `SUPERHARNESS_SUMMARIZER=...` persists per-project without shell rc plumbing.

### Branch state

On `docs/claude-mem-integration`, six commits ahead of main once this commits: docs-only, iter 1-4, iter 5-6 plus canon, iter 7, iter 8, iter 9. Not pushed.

---

## 2026-05-11 session (latest): cross-process rate limit + sibling citation routes

### What landed

Three follow-ups from the previous HANDOFF deferred list, all in one iteration. The in-memory rate limiter now has a SQLite-backed sibling for the cross-process case; sibling JSON routes expose handoff/decision/failure rows alongside observations; the same `summarizer_calls` table that backs rate limiting is the foundation for future cost tracking.

| Surface | Files | Tests |
|---------|-------|-------|
| Migration v14 + `summarizer_calls` DAO | `engine/db.py`, `engine/summarizer_calls.py` (new) | 11 |
| SQLite-backed rate limiter (`_SQLiteRateLimitedSummarizer`) | `engine/summarizer.py` | 7 |
| Citation route helpers + dashboard wiring | `commands/citation.py` (new), `scripts/dashboard-ui.py` | 14 |
| Capture wire-through (`project_dir`) | `engine/observation_capture.py`, `engine/state_writer.py` | (existing tests cover) |

32 new unit tests, all GREEN. Schema v13 to v14 with idempotent migration. No new third-party dependencies.

### Cross-process rate limit

`get_summarizer(name, *, project_dir=...)`. When `project_dir` is set the returned wrapper is the SQLite-backed `_SQLiteRateLimitedSummarizer`, which:

1. Queries `count_in_window()` on the `summarizer_calls` table before each call.
2. Logs every call (success or transport failure) via `record_call()`.
3. Counts successes only for budget purposes (transient failures do not eat the budget).
4. Degrades open: a DAO fault (e.g. bad project dir) is swallowed so a broken state DB cannot block lifecycle transitions.

The auto-capture path in `state_writer.set_task_status` passes its own `project_dir` into `capture_observation`, which forwards into `get_summarizer`. Multiple `shux` processes against the same project dir now share one budget.

The in-memory bucket remains available for callers that do not (or cannot) pass a `project_dir`.

### Sibling citation routes

`commands/citation.py` exposes `route_citation(conn, kind, raw_id)` for kinds `observation`, `handoff`, `decision`, `failure`. Reuses the iter-4 id-parser. The dashboard's `do_GET` gains four new branches:

- `GET /api/handoff/<id>` — handoff row by id (metadata pre-parsed from JSON)
- `GET /api/decision/<id>` — decision row by id
- `GET /api/failure/<id>` — failure row by id
- `GET /api/task/<task_id>/observations` — list of observation snapshots for a task, ordered oldest first

All return JSON; status 200 / 404 / 400 as in iter 4. HTML rendering on task pages stays deferred.

### Cost-tracking foundation

`summarizer_calls` has `input_tokens` and `output_tokens` columns ready. Providers in `summarizer_providers.py` still return strings only; token extraction from API responses is a follow-up. Once wired, `shux insights` gains a per-provider spend roll-up with no further schema work.

### Files changed this commit

- `docs/PLAN-claude-mem-integration.md` (iteration 8 section appended)
- `src/superharness/engine/db.py` (schema v13 → v14, `_migration_v14`)
- `src/superharness/engine/summarizer_calls.py` (new DAO)
- `src/superharness/engine/summarizer.py` (`_SQLiteRateLimitedSummarizer`, project_dir-aware `get_summarizer`)
- `src/superharness/engine/observation_capture.py` (`project_dir` kwarg)
- `src/superharness/engine/state_writer.py` (pass `project_dir` to capture)
- `src/superharness/commands/citation.py` (new)
- `src/superharness/scripts/dashboard-ui.py` (four new route branches)
- `tests/unit/test_summarizer_calls_dao.py` (new)
- `tests/unit/test_summarizer_sqlite_rate_limit.py` (new)
- `tests/unit/test_citation_routes.py` (new)
- `HANDOFF.md` (this section)
- `CHANGELOG.md` (appended)

### What the next session should do

- Token usage extraction from each provider's response (Anthropic `usage.input_tokens/output_tokens`, OpenAI-compatible `usage.prompt_tokens/completion_tokens`, Gemini `usageMetadata.promptTokenCount/candidatesTokenCount`). Pass the numbers into `record_call()` so the cost columns get real data.
- `shux insights` extension: per-provider call counts and (once tokens flow) per-provider spend over the last 7/30 days.
- HTML rendering on task pages in the dashboard: observation cards plus inline links for `see decision/42` style references. Sibling routes are ready; only the template work remains.
- Consider a `shux observation list <task-id>` CLI mirror of the per-task route once the auto-capture loop has populated real rows.

### Branch state

On `docs/claude-mem-integration`, five commits ahead of main once this commits: docs-only, iter 1-4, iter 5-6 plus canon, iter 7, iter 8. Not pushed.

---

## 2026-05-11 session (latest): provider summarizers + rate limiting

### What landed

Iteration 7 adds five external provider summarizers, a per-process rate limiter, and an opt-in smoke test suite. The protocol from iter 5 is unchanged; new providers self-register into the upgraded registry.

| Surface | Files | Tests |
|---------|-------|-------|
| Config-based registry + rate limiter | `engine/summarizer.py` (rewrite, backwards-compatible) | 10 rate-limit tests |
| 5 provider classes (Anthropic, Gemini, OpenAI, OpenRouter, OpenCode) | `engine/summarizer_providers.py` (new) | 19 provider tests |
| Opt-in real-network smoke | `tests/integration/test_summarizer_smoke.py` (new) | 5 (gated, skip by default) |

29 new unit tests (40 in the summarizer area total). Smoke tests skip cleanly when `RUN_PROVIDER_SMOKE=1` is unset. No new external dependencies: HTTP providers use stdlib `urllib.request` via a shared `_http_post_json()` helper.

### How to use a real provider

```bash
export ANTHROPIC_API_KEY=sk-...
export SUPERHARNESS_SUMMARIZER=anthropic
# next report_ready transition produces an LLM-generated snapshot
```

Same shape for `gemini` (env `GEMINI_API_KEY` or `GOOGLE_API_KEY`), `openai`, `openrouter`, `opencode` (requires `opencode` on PATH).

Per-provider default models (overridable in registry init kwargs):
- anthropic: `claude-haiku-4-5-20251001`
- gemini: `gemini-2.0-flash`
- openai: `gpt-4o-mini`
- openrouter: `anthropic/claude-haiku-4.5`
- opencode: whatever OpenCode is configured for

### Rate limit

Default budgets in registry: 60/hour for HTTP providers, 30/hour for OpenCode, unlimited for Noop. Override globally with `SUPERHARNESS_SUMMARIZER_MAX_PER_HOUR=N` (set to 0 to disable). Bucket is in-memory, per-process. If the watcher and a CLI both fire transitions, they have independent buckets. Cross-process limiting would need a SQLite-backed table; deferred.

When a bucket is exhausted, `RateLimitExceeded` raises, the auto-capture caller in `observation_capture` catches it, and that single snapshot is skipped. The lifecycle transition still succeeds.

### Smoke tests

`tests/integration/test_summarizer_smoke.py`. Gate: `RUN_PROVIDER_SMOKE=1`. Per-test skip if the relevant API key (or `opencode` binary) is missing. Costs cents at most against the cheap default models. CI never runs them.

```bash
RUN_PROVIDER_SMOKE=1 ANTHROPIC_API_KEY=sk-... pytest tests/integration/test_summarizer_smoke.py::test_anthropic_smoke -v
```

### OpenCode caveat

Subprocess-based. Slower than HTTP providers (~500ms-1s startup overhead). Parses stdout. Default invocation is `opencode run <prompt>`; configurable via `binary`/`subcommand` kwargs if your OpenCode version differs. Marked experimental in the module docstring.

### Files changed this commit

- `docs/PLAN-claude-mem-integration.md` (iteration 7 section appended)
- `src/superharness/engine/summarizer.py` (config registry, rate limiter, lazy provider load)
- `src/superharness/engine/summarizer_providers.py` (new, 5 providers + registration)
- `tests/unit/test_summarizer_providers.py` (new)
- `tests/unit/test_summarizer_rate_limit.py` (new)
- `tests/integration/test_summarizer_smoke.py` (new, opt-in)
- `HANDOFF.md` (this section)
- `CHANGELOG.md` (appended)

### What the next session should do

- Cross-process rate limit (SQLite-backed `summarizer_calls` table) if the in-memory bucket leaks past its budget under real load.
- Dashboard surface for observation snapshots: priority-3 from `docs/AUDIT-claude-mem-adaptation.md`. Sibling routes (`/api/handoff/<id>`, `/api/decision/<id>`, `/api/failure/<id>`) plus HTML rendering on each task page. Makes the dashboard a full audit trail.
- Provider cost tracking. Each successful summarize call could log model + input/output tokens to a `summarizer_calls` table for `shux insights` to roll up.

### Branch state

On `docs/claude-mem-integration`, four commits ahead of main once this commits: docs-only, iter 1-4, iter 5-6 plus canon, iter 7. Not pushed.

---

## 2026-05-11 session (late): summarizer + auto-capture + claude-mem in canon

### What landed (code)

Two more iterations from the plan. The observation-storage layer shipped earlier now has a producer.

| Iter | Surface | Files added or changed | Tests |
|------|---------|------------------------|-------|
| 5 | Summarizer protocol + Noop default + env-driven registry | `engine/summarizer.py` | 11 |
| 6 | `capture_observation()` + report_ready transition hook in `state_writer` | `engine/observation_capture.py`, `engine/state_writer.py` (5-line hook) | 6 + 3 integration |

Total: 20 new unit tests, all GREEN. The Noop summarizer is deterministic and network-free so the loop runs offline by default. Provider-backed summarizers (Anthropic, Gemini, OpenRouter) plug into the same protocol later when a real workload demands them.

### What landed (docs, prior-art canon)

claude-mem is now in the same canonical "prior art and influences" surface as hermes, pi, paperclip, dorothy, superpowers, Ralph Loops. Three docs touched:

- `README.md` — new bullet in "Prior art and influences" pointing at the AUDIT/CONCEPT/PLAN trio.
- `ATTRIBUTIONS.md` — full section in long form: Adopted (privacy strip, env-var isolation, observation table, citation URL pattern, plan-then-implement discipline) and Did not adopt (auto-injection, Express/React viewer, OAuth-in-worker, curl|bash installer, auto-bump-deps daily, 30-language translation, BullMQ/ioredis/Postgres, Chroma MCP, Pro/SaaS patterns).
- `docs/AUDIT-claude-mem-adaptation.md` — new audit doc mirroring `AUDIT-pi-hermes-adaptation.md`: Guiding Principle, Comparison table, Already Shipped, Recommended Next Picks priority-ordered, What NOT to Pick, What Each Side Wins On.

### Capture loop end-to-end

When a task transitions to `report_ready` via `state_writer.set_task_status`:

1. Existing logic runs (validation, version bump, timestamp, event_stream write, inbox guard).
2. The new branch resolves the configured summarizer via `get_summarizer()` (defaults to Noop).
3. `observation_capture.capture_observation()` builds a context dict from the task row plus the most recent report-phase handoff, runs it through the summarizer, strips private tags, and inserts into `task_observations`.
4. Two try/except layers wrap the path: one in `capture_observation()` returning None on any internal fault, one around the call site in `state_writer`. A failing summarizer cannot break a status transition.

### Still deferred (with rationale)

- Provider-backed summarizers: defer until there is a felt need for real LLM summaries. The Noop default ships value today (deterministic, queryable rows).
- HTML rendering of observations on the dashboard: defer until the operator wants UI-level audit trails. JSON renders fine for now.
- Sibling routes for `/api/handoff/<id>`, `/api/decision/<id>`, `/api/failure/<id>`: ship when agents are instructed to cite by ID in plans. Id-parser is already extracted; each route is roughly fifteen minutes.
- Refactoring existing call sites to use `utils.paths.resolve_state_db_path()`: defer until multi-profile collisions are actually felt.

### Files changed this commit

- `docs/PLAN-claude-mem-integration.md` (iterations 5 and 6 sections appended)
- `docs/AUDIT-claude-mem-adaptation.md` (new)
- `README.md` (Prior art bullet)
- `ATTRIBUTIONS.md` (claude-mem section)
- `src/superharness/engine/summarizer.py` (new)
- `src/superharness/engine/observation_capture.py` (new)
- `src/superharness/engine/state_writer.py` (5-line hook in `set_task_status`)
- `tests/unit/test_summarizer.py` (new)
- `tests/unit/test_observation_capture.py` (new)
- `tests/unit/test_set_status_triggers_capture.py` (new)
- `HANDOFF.md` (this section)
- `CHANGELOG.md` (appended)

### What the next session should do

If a real LLM summary is wanted: implement `AnthropicSummarizer` against the Claude Agent SDK pattern superharness already uses for dispatch. Register it in `_REGISTRY` and provide a `~/.superharness/.env` example. Keep the Noop default so tests stay offline. Two-hour estimate.

If dashboard audit-trail UI is wanted: implement priority-3 from the AUDIT doc (sibling citation routes) plus a small HTML view that renders observation cards on each task page. Reuse the existing dashboard HTML scaffolding.

### Branch state

On `docs/claude-mem-integration`. Three commits ahead of main once this commits: docs-only, iterations 1-4, iterations 5-6 plus canon. Not pushed.

---

## 2026-05-11 session: claude-mem integration, iterations 1-4 implemented

### What landed

Four foundational iterations from `docs/PLAN-claude-mem-integration.md`. All added as additive modules. Zero existing call sites refactored. Full unit suite: 2422 passed, 553 skipped, 0 failed.

| Iter | Surface | Files added | Tests |
|------|---------|-------------|-------|
| 1 | privacy strip utility | `utils/privacy.py` | 14 |
| 2 | path/port resolver | `utils/paths.py` | 11 |
| 3 | task_observations table + DAO, schema v13 | `engine/observations_dao.py`, migration in `engine/db.py` | 14 |
| 4 | `/api/observation/<id>` route + `shux observation show` CLI | `commands/observation.py`, dashboard route branch, CLI registration | 15 |

54 new unit tests, all GREEN. Schema bumped from v12 to v13 with idempotent migration. New CLI command `shux observation show <id>` exits 0/1/2 for found/missing/invalid id.

### Explicitly deferred

- Observation auto-capture on `report_ready` transition. Needs a summarizer adapter interface and provider-key handling. Lands once the storage layer sees real use.
- HTML rendering of observations on the dashboard. JSON-only for now.
- Refactoring existing call sites to the new path resolver. They opt in over time.
- `/api/handoff/<id>`, `/api/decision/<id>`, `/api/failure/<id>` routes. The id-parser in `commands/observation.py` is the natural extension point.

### Files changed

- `docs/PLAN-claude-mem-integration.md` (new)
- `src/superharness/utils/privacy.py` (new)
- `src/superharness/utils/paths.py` (new)
- `src/superharness/engine/observations_dao.py` (new)
- `src/superharness/engine/db.py` (schema v13)
- `src/superharness/commands/observation.py` (new)
- `src/superharness/cli.py` (register observation group)
- `src/superharness/scripts/dashboard-ui.py` (route branch)
- `tests/unit/test_privacy_strip.py` (new)
- `tests/unit/test_paths_resolver.py` (new)
- `tests/unit/test_observations_dao.py` (new)
- `tests/unit/test_observation_route.py` (new)
- `tests/unit/test_observation_show_cli.py` (new)
- `HANDOFF.md` (this section)
- `CHANGELOG.md` (appended)

### What the next session should do

1. Design the summarizer adapter interface (provider-agnostic: takes a task id + transition phase, returns a summary string). Land it as iteration 5 with TDD on a mock summarizer first.
2. Wire the summarizer into the `report_ready` transition. Operator gate stays intact: the snapshot is stored, not auto-injected.
3. Optional: backfill existing call sites to use `utils.paths.resolve_state_db_path()`.

### Branch state

On `docs/claude-mem-integration`, two commits ahead of main. Not pushed.

---

## 2026-05-11 session: claude-mem integration proposal (docs only)

### What was added

`docs/CONCEPT-claude-mem-integration.md`: ranked list of features worth borrowing from `thedotmack/claude-mem` v13.0.1, scoped to what superharness does not already have (`operator_memory.py`, FTS5 recall, claude-code and codex-cli adapters, dashboard at `:8787`, `shux schedule`).

### Why this matters

`claude-mem` and superharness solve adjacent problems (per-agent memory vs multi-agent coordination). A few mechanisms compose cleanly without breaking operator gating. The doc captures which ones, ranked by value-to-cost, and which to skip. No code or version bump in this session.

### High-value integration candidates (from the doc)

1. Observation snapshot at `report_ready` transition (new `task_observations` table).
2. Privacy tag stripping at every handoff write boundary.
3. Citations: stable URL views for handoff, decision, failure IDs in the dashboard.
4. `SUPERHARNESS_DATA_DIR` env var for per-profile isolation, mirroring `CLAUDE_MEM_DATA_DIR`.

### Files changed

- `docs/CONCEPT-claude-mem-integration.md` (new)
- `HANDOFF.md` (this section)
- `CHANGELOG.md` (one appended line)

### What the next session should do

Convert items 1 through 4 into `shux task create` entries when ready to schedule. No work to commit beyond this docs-only patch. Branch `docs/claude-mem-integration` is local, not pushed.

### Branch state

On `docs/claude-mem-integration`, three tracked files modified. Untracked files in `.superharness/` and `docs/PLAN-ralph-extraction.md` from prior sessions are deliberately left out of this commit.

---

## 2026-05-08 PM session: Portable-paths cleanup planning

### What was added

Two planning docs in `docs/`. **No code changes to superharness in this session**
(a `fix/session-stop-no-mcp-kill` branch was created and immediately reverted
once the user pointed out that the upstream pkill block should not be silently
patched in their dev source tree).

| File | Purpose |
|------|---------|
| `docs/PLAN-portable-adapter-paths.md` | Per-project context: superharness needs a `superharness adapter-path <host> <hook>` CLI subcommand so external configs can resolve hook paths without hardcoding repo locations. Acceptance test included. |
| `docs/PLAN-portable-paths-cleanup.md` | Master TDD plan for the cross-repo cleanup. 4 phases: (1) superharness CLI, (2) obsidian-semantic-mcp launcher, (3) voice-toolkit docs, (4) agent-config migration. Phases 1-3 are independent; phase 4 depends on 1-3. |

### Why this matters

Agent configs (`~/.claude/settings.json`, `~/.claude.json`, `~/.opencode.json`,
`~/.pi/agent/mcp.json`) hardcode absolute paths to this repo's adapter hook
scripts. The same problem affects three projects. This session diagnosed the
root cause and wrote the cross-cutting plan but did NOT execute on superharness.

Specifically, `~/.claude/settings.json` lines 209/245/277/287/308 reference
`bash /Users/airm2max/DevOpsSec/superharness/src/superharness/adapters/claude-code/hooks/<hook>.sh`
which breaks under (a) repo moves, (b) release installs (`pip install
superharness`), (c) temp worktrees (a stale worktree path was already found and
fixed in `settings.json` earlier this session).

### What other projects shipped this session (for context)

- **voice-toolkit** — `chore/portable-mcp-config` branch (uncommitted): `_find_binary()` resolution order fixed (PATH-installed > source-relative). 5 new tests pass.
- **obsidian-semantic-mcp** — `chore/portable-mcp-config` branch (uncommitted): stdin reader rewritten to use `anyio.to_thread.run_sync(readline)`, fixing the 30s pipe-stdin hang that broke MCP over `docker exec`. 7 new tests. Image rebuild still pending.

### What the next session should do (superharness-specific)

1. **Phase 1 — implement `superharness adapter-path` CLI** per
   `docs/PLAN-portable-adapter-paths.md`. RED test, GREEN minimal impl
   using `importlib.resources`, REFACTOR to consume manifests from
   `adapter_manifests/*.yaml`.
2. **Phase 4 (after phase 1 ships)** — migrate `~/.claude/settings.json`
   to call `bash $(superharness adapter-path claude-code <hook>)` instead
   of hardcoded paths. The Stop hook is currently routed through
   `~/.claude/hooks/superharness-stop-no-mcp-kill.sh` (a local wrapper
   that strips the MCP-kill block from `session-stop.sh`); that wrapper
   should also be updated to use `superharness adapter-path` once
   phase 1 ships.
3. **Consider an upstream fix** to `session-stop.sh`: drop the trailing
   `pkill -TERM -f` block entirely. Claude Code already cleans up stdio
   MCP children on CLI exit, and the Stop event fires per-turn (not at
   session end), so pkill-ing here breaks long-lived MCP connections
   between turns. If accepted upstream, the local wrapper can be deleted.

### Cross-cutting follow-ups (not superharness's responsibility)

- Rebuild & publish obsidian-semantic-mcp image (owner-driven).
- Re-register voice-toolkit in `~/.opencode.json` to overwrite the stale
  absolute path now that `_find_binary()` resolves correctly.

---

## 2026-05-07 session: Watcher bug fixes

Three watcher bug fixes + regression test suites. All changes are on `feat/test-unification-task`, not yet committed.

### Fix 1 — Flood prevention: `auto_enqueue_approved()` in `inbox_watch.py`

Root cause of the 53-item flood bug: `auto_enqueue_approved()` only blocked re-enqueue of **active** (pending/launched/running) items. When dispatch failed, the item left the active set and the next watcher tick created a fresh item at `retry_count=0`, looping forever.

Three sub-fixes:
- **`failed_counts` guard**: COUNT failed items per task from SQLite; skip re-enqueue when `failed_counts[task_id] >= max_retries`
- **`StateError` catch**: wrapped `inbox_dao.enqueue` in `try/except` to swallow race-condition duplicates gracefully
- **YAML sync fix**: appended `new_items` (SQLite-only) not already in `current_items` back to YAML — fixed 2 pre-existing test failures in `test_auto_dispatch.py`

4 regression tests: `tests/unit/test_auto_enqueue_flood_prevention.py`

### Fix 2 — Zombie max-age cap: `_reconcile_zombies()` in `inbox_watch.py`

Root cause of the 406-minute stale launched item: alive-PID non-plan-only items had no wall-clock cap — the reconciler just `continue`d past them forever.

Added **Check 2c**: non-plan-only launched items with alive PIDs running > 2 hours get SIGTERM'd and marked failed. Plan-only items keep the existing 15-min cap (Check 2b). Updated docstring to list all 5 checks.

4 regression tests: `tests/unit/test_reconcile_zombie_max_age.py`

### Fix 3 — Auto-archive handoff filter: `_auto_archive_stale_tasks()` in `inbox_watch.py`

Root cause of stale `in_progress` tasks not being archived: the handoff check used `if handoffs: continue` — any handoff file, including a plan-phase one, blocked auto-archive. A task with a plan handoff from a failed gemini dispatch would sit `in_progress` indefinitely.

Fix: only `-report-` or `-done-` filenames exempt a task. Plan handoffs (`-plan-`) are ignored for the archive decision.

5 regression tests: `tests/unit/test_auto_archive_stale_tasks.py`

## Files changed (not yet committed)

- `src/superharness/commands/inbox_watch.py` — 3 fixes above
- `tests/unit/test_auto_enqueue_flood_prevention.py` — new (4 tests)
- `tests/unit/test_reconcile_zombie_max_age.py` — new (4 tests)
- `tests/unit/test_auto_archive_stale_tasks.py` — new (5 tests)

## First thing next session

Commit and PR all 3 fixes as a single patch:

```bash
git add src/superharness/commands/inbox_watch.py \
        tests/unit/test_auto_enqueue_flood_prevention.py \
        tests/unit/test_reconcile_zombie_max_age.py \
        tests/unit/test_auto_archive_stale_tasks.py \
        CHANGELOG.md HANDOFF.md
git commit -m "fix(watcher): flood prevention, zombie max-age cap, auto-archive handoff filter (vX.Y.Z)"
gh pr create ...
```

Bump version (patch: fix commit) in `pyproject.toml` + `CHANGELOG.md` before committing.

Also: PR #190 (`fix/auto-dispatch-valid-agents-v1.47.5`) may still be open — check `gh pr list` and merge first if so.

## Tasks completed this session (report_ready — awaiting shux close)

- `feat.dashboard-auto-restart-on-upgrade` — report_ready (implementation verified, 8/8 tests GREEN)
- `feat.refactor-do-dispatch-decomposition` — report_ready (decomposition was already done, dead stubs removed, 11 tests added)

## Known remaining issues

- Pre-existing CI failures on unit/integration/E2E (same failures on `main`) — `test_enqueue_writes_inbox` is the main one (SQLite-only mode doesn't write `inbox.yaml`). Tracked separately.
- Watcher lock hash differs between Python environments (pyenv 3.11 vs pipx/homebrew 3.14) — each computes a different hash for the same project path, so two instances can both think they hold the lock. Fix: normalize to `os.path.realpath()` in `watcher_lock_path()`.
- `_classify_task()` in `auto_dispatch.py` still has a hardcoded `mini→codex-cli / else→claude-code` tier mapping — needs model router awareness of all 4 agents. Low urgency.

## Previous roadmap items (deferred)

- **PR #2-B**: split-brain test fixtures (`test_task_workflow_v2_phase1.py`, `test_task_failed_reason.py`)
- **PR #2-C**: reconciler bugs (`_reconcile_zombies` never defined, `zombie_reconcile.py` missing)
- **PR #3-B**: ancillary commands YAML→SQLite (`onboard.py`, `inbox_watch.py`, `handoff_write.py`, `recap.py`, `preflight.py`, `recall.py`)
