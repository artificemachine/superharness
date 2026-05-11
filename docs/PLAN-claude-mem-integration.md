# Plan: claude-mem integration, iteration-by-iteration

Date: 2026-05-11
Branch: `docs/claude-mem-integration`
Source of requirements: `docs/CONCEPT-claude-mem-integration.md`
Mode: TDD (red, green, refactor) for each iteration, with unit tests at minimum and integration coverage where the surface justifies it.

## Scope discipline

Each iteration is a vertical slice that lands on its own. Iterations 1 and 2 are pure additions (utility modules) with zero callers refactored. Iterations 3 and 4 add a storage layer and a read-only route. No write paths refactor across the codebase. No LLM summarizer in this pass.

## Iteration 1: privacy tag stripping utility

**Acceptance criteria**

1. `superharness.utils.privacy.strip_private_tags(text)` returns the input with every `<private>...</private>` span removed.
2. Stripping is non-greedy, handles multiple spans, newlines inside spans, and unmatched tags (unmatched left as-is, no exception).
3. Returns the empty string when input is None or empty.
4. Idempotent: `strip(strip(x)) == strip(x)`.

**TDD**

- RED: `tests/unit/test_privacy_strip.py` with cases for single span, multiple spans, multiline content, no tags, unmatched open tag, empty/None input, idempotence.
- GREEN: smallest regex implementation in `src/superharness/utils/privacy.py`.
- REFACTOR: extract the compiled regex to module level, add a public `PRIVATE_TAG_RE` constant for reuse.

**Files**

- `src/superharness/utils/privacy.py` (new)
- `tests/unit/test_privacy_strip.py` (new)

## Iteration 2: SUPERHARNESS_DATA_DIR env var resolver

**Acceptance criteria**

1. `superharness.utils.paths.resolve_project_dir(default)` returns `os.environ["SUPERHARNESS_DATA_DIR"]` if set, otherwise the default.
2. `superharness.utils.paths.resolve_state_db_path(project_dir)` returns `<project_dir>/.superharness/state.sqlite3`.
3. `superharness.utils.paths.resolve_dashboard_port(default)` returns `int(os.environ["SUPERHARNESS_DASHBOARD_PORT"])` if set, otherwise the default. Validates 1024-65535 range, raises ValueError otherwise.
4. Resolver is pure (no I/O). Existing call sites are not refactored in this iteration. They opt in later.

**TDD**

- RED: `tests/unit/test_paths_resolver.py` covers env-set, env-unset, dashboard port valid/invalid, state db path formatting.
- GREEN: minimal `paths.py` with three functions.
- REFACTOR: dedup env-read into a single helper.

**Files**

- `src/superharness/utils/paths.py` (new)
- `tests/unit/test_paths_resolver.py` (new)

## Iteration 3: task_observations storage layer

**Acceptance criteria**

1. Schema migration v13 in `engine/db.py` creates a `task_observations` table:
   - `id` INTEGER PK autoincrement
   - `task_id` TEXT NOT NULL
   - `phase` TEXT NOT NULL (e.g. `report_ready`)
   - `summary` TEXT NOT NULL
   - `created_at` TEXT NOT NULL
   - index on `task_id`
2. `engine.observations_dao` exposes `insert(conn, task_id, phase, summary)`, `get_by_id(conn, id)`, `list_for_task(conn, task_id)`.
3. `insert()` strips private tags from `summary` before write (uses Iteration 1 utility).
4. Migration is idempotent: running on an already-migrated DB is a no-op.

**TDD**

- RED: `tests/unit/test_observations_dao.py` for insert/get/list happy path, privacy strip on insert, empty list for unknown task, ordering by created_at.
- GREEN: write `observations_dao.py` and add migration branch in `_run_migrations()`.
- REFACTOR: match the existing operator_memory DAO style for naming and connection handling.

**Files**

- `src/superharness/engine/observations_dao.py` (new)
- `src/superharness/engine/db.py` (bump `CURRENT_SCHEMA_VERSION` to 13, add migration step)
- `tests/unit/test_observations_dao.py` (new)

**Explicitly out of scope**

- No transition hook on `report_ready`. The DAO is the foundation. Auto-capture lands in a separate iteration once the summarizer interface is designed.
- No LLM call. The DAO accepts a pre-built summary string. The summarizer adapter is future work.

## Iteration 4: observation citation route on the dashboard

**Acceptance criteria**

1. New route `GET /api/observation/<id>` on the dashboard:
   - Returns 200 with JSON `{id, task_id, phase, summary, created_at}` when the row exists.
   - Returns 404 with JSON `{error: "not found"}` when absent.
   - Returns 400 with JSON `{error: "invalid id"}` when id is not a positive integer.
2. New CLI `shux observation show <id>` prints the same JSON to stdout, exits 0 on found, 1 on not found, 2 on invalid id.
3. The route and CLI share the same DAO from Iteration 3.

**TDD**

- RED: `tests/unit/test_observation_route.py` constructs a fake handler and asserts response shape for each status code. RED: `tests/unit/test_observation_show_cli.py` for the CLI.
- GREEN: route branch added to `do_GET` in `dashboard-ui.py`. CLI added as a new command module wired into the click group.
- REFACTOR: extract the id parser to a small helper for reuse with future `/api/decision/<id>` and `/api/failure/<id>` routes.

**Files**

- `src/superharness/scripts/dashboard-ui.py` (add route branch + helper)
- `src/superharness/commands/observation.py` (new CLI module)
- `src/superharness/cli.py` (register new command)
- `tests/unit/test_observation_route.py` (new)
- `tests/unit/test_observation_show_cli.py` (new)

**Explicitly out of scope**

- No HTML rendering. JSON-only response. The HTML view is future work, gated on whether agents start citing observations in practice.
- No `/api/handoff/<id>`, `/api/decision/<id>`, `/api/failure/<id>` routes in this pass. The id-parser refactor leaves them as natural extension points.

## Iteration 5: summarizer adapter

**Acceptance criteria**

1. `engine.summarizer.Summarizer` protocol with one method `summarize(context: dict) -> str`.
2. `engine.summarizer.NoopSummarizer` is deterministic, network-free, and produces a non-empty summary from a context dict. Strips private tags from anything it embeds.
3. `engine.summarizer.get_summarizer(name=None)` returns a Summarizer; resolves explicit name first, then `SUPERHARNESS_SUMMARIZER` env, then `"noop"`. Unknown names raise `SummarizerError`.
4. No external network calls in this iteration. Anthropic/Gemini/OpenRouter providers are out of scope; they plug into the protocol later.

**TDD**

- RED: `tests/unit/test_summarizer.py` for protocol compliance, noop output shape, idempotence, env-driven selection, unknown-provider rejection.
- GREEN: `engine/summarizer.py` with Protocol + Noop + registry.
- REFACTOR: extract the env var name to a module constant.

**Files**

- `src/superharness/engine/summarizer.py` (new)
- `tests/unit/test_summarizer.py` (new)

## Iteration 6: auto-capture on report_ready transition

**Acceptance criteria**

1. `engine.observation_capture.capture_observation(conn, task_id, phase, summarizer=None)` builds a context dict from the task row plus the latest report-phase handoff, runs it through the resolved summarizer, and inserts via `observations_dao`. Returns the new observation id, or None on any internal failure.
2. The function never raises. Every internal exception is caught and surfaced as None.
3. `engine.state_writer.set_task_status` invokes the capture exactly when the new status is `report_ready`. The capture call is wrapped in its own try/except so a failure cannot break the transition.
4. Other status transitions do not trigger the capture.

**TDD**

- RED: `tests/unit/test_observation_capture.py` for happy path with and without a report handoff, unknown task returns None, summarizer-exception swallowed, privacy strip flows through.
- RED: `tests/unit/test_set_status_triggers_capture.py` verifying transition-to-report_ready inserts a row, other transitions insert none, monkey-patched capture failure does not break the transition.
- GREEN: `engine/observation_capture.py` and a five-line block in `engine/state_writer.py`.
- REFACTOR: keep capture out of `state_writer` hot path; module-level import inside the if branch is acceptable because it only runs on report_ready transitions, not on every status change.

**Files**

- `src/superharness/engine/observation_capture.py` (new)
- `src/superharness/engine/state_writer.py` (5-line hook)
- `tests/unit/test_observation_capture.py` (new)
- `tests/unit/test_set_status_triggers_capture.py` (new)

**Explicitly out of scope (still deferred)**

- Provider-backed summarizers (Anthropic, Gemini, OpenRouter). The protocol is in place; concrete providers land when a real workload needs them. The Noop default keeps tests deterministic and the loop runs offline.
- HTML rendering of observations on the dashboard.
- Sibling routes for `/api/handoff/<id>`, `/api/decision/<id>`, `/api/failure/<id>`. The id-parser is the natural extension point.
- Refactoring existing call sites to the new path resolver.

## Iteration 7: provider-backed summarizers + rate limiting

**Acceptance criteria**

1. Five external providers registered into the existing summarizer registry: `anthropic`, `gemini`, `openai`, `openrouter`, `opencode`. Each plugs into the `Summarizer` protocol so the call site in `observation_capture` does not change.
2. HTTP providers use stdlib `urllib.request` via a shared `_http_post_json()` helper. No new third-party SDK dependencies.
3. `AnthropicSummarizer` and `GeminiSummarizer` speak their native APIs. `OpenAISummarizer` and `OpenRouterSummarizer` share a `ChatCompletionsSummarizer` base for the OpenAI-compatible shape.
4. `OpenCodeSummarizer` subprocesses the local `opencode` CLI. Experimental: documented slower (subprocess startup overhead, stdout parsing). Refuses to construct when the binary is missing.
5. Construction raises `SummarizerError` when the required API key env var (or binary) is missing. Transport faults raise `SummarizerError` too. The auto-capture caller in `observation_capture` catches every exception and skips silently.
6. `_REGISTRY` becomes `dict[str, SummarizerConfig]`. Each config holds `provider_class`, `max_per_hour`, `default_model`. Backwards-compatible with the existing noop registration.
7. Per-process rate limiter (`_RateLimitedSummarizer`) wraps any provider with `max_per_hour` set. Default budgets: 60/hour for HTTP providers, 30/hour for OpenCode, unlimited for Noop. Overridable by `SUPERHARNESS_SUMMARIZER_MAX_PER_HOUR`. Exceeding the budget raises `RateLimitExceeded` (a `SummarizerError` subclass).
8. Opt-in smoke tests under `tests/integration/test_summarizer_smoke.py` gated by `RUN_PROVIDER_SMOKE=1` plus per-provider credentials. CI never runs them; local-only verification.

**TDD**

- RED: `tests/unit/test_summarizer_providers.py` covers construction failures (missing creds, missing binary), HTTP round-trip (mocked `_http_post_json`), subprocess round-trip (mocked `subprocess.run`), ANSI stripping in OpenCode output, private-tag stripping in every provider's output, registry presence of all five names.
- RED: `tests/unit/test_summarizer_rate_limit.py` covers under-budget pass-through, at-budget raise, expiration of old calls, env override (zero disables, invalid falls back), wrapping behaviour of `get_summarizer`, integration with `capture_observation` (rate-limit error returns None, never raises).
- GREEN: refactor `summarizer.py` registry to config-based, add `_RateLimitedSummarizer`, `RateLimitExceeded`, `SummarizerConfig`, `register_summarizer`, `list_summarizers`, `_resolve_max_per_hour`. New `summarizer_providers.py` defines the five providers and self-registers at import time. `summarizer.py` imports the providers module at the bottom to trigger registration.
- REFACTOR: extract `_build_prompt`, `_http_post_json`, `_DEFAULT_TIMEOUT_S`, `_DEFAULT_MAX_TOKENS`, `_ANSI_RE` to module level in providers. `ChatCompletionsSummarizer` is the DRY base for OpenAI-compatible endpoints.

**Files**

- `src/superharness/engine/summarizer.py` (rewrite: config registry, rate limiter, lazy provider load)
- `src/superharness/engine/summarizer_providers.py` (new)
- `tests/unit/test_summarizer_providers.py` (new)
- `tests/unit/test_summarizer_rate_limit.py` (new)
- `tests/integration/test_summarizer_smoke.py` (new, opt-in)

**Explicitly out of scope**

- Cross-process rate limiting (SQLite-backed bucket). In-memory bucket is per-process; multiple `shux` processes have independent buckets. Lands if the operator hits real contention.
- Credential storage in `~/.superharness/.env`. Env vars are read directly from the process environment. Adding a dotenv loader is a separate, broader change.
- Streaming responses. The summary prompt is short and one-shot.
- Cost reporting per provider. The dashboard already has a `budget` signal; wiring summarizer cost in is future work.

## Iteration 8: cross-process rate limit + cost-tracking log + sibling citation routes

**Acceptance criteria**

1. Migration v14 adds `summarizer_calls(id, provider, model, called_at, success, input_tokens, output_tokens)` plus index on `(provider, called_at)`. Idempotent.
2. `engine.summarizer_calls` DAO exposes `record_call(provider, success, model?, input_tokens?, output_tokens?)` and `count_in_window(provider, window_seconds, include_failures=False)`. Rate-limit consumers leave `include_failures=False` so transient transport errors do not eat the budget.
3. New `_SQLiteRateLimitedSummarizer` wraps a provider with a SQLite-backed budget read from `summarizer_calls`. Multiple processes against the same project dir share one budget. DAO faults degrade open (limiter allows the call). Both successes and failures are logged.
4. `get_summarizer(name=None, *, project_dir=None)` returns the SQLite-backed wrapper when `project_dir` is set, the in-memory wrapper otherwise. Backwards-compatible: existing callers without `project_dir` keep the per-process bucket.
5. `capture_observation(..., *, project_dir=None)` threads `project_dir` through to `get_summarizer`. The `state_writer.set_task_status` hook passes its own `project_dir` so auto-capture uses the cross-process budget.
6. New `commands.citation` module with `route_citation(conn, kind, raw_id) -> (payload, status)` covering kinds `observation`, `handoff`, `decision`, `failure`. Reuses the iter-4 id-parser. Plus `route_task_observations(conn, task_id) -> (payload, status)` for the per-task list.
7. Dashboard wires four new routes: `/api/handoff/<id>`, `/api/decision/<id>`, `/api/failure/<id>`, `/api/task/<task_id>/observations`. JSON only; HTML rendering on task pages remains deferred.

**TDD**

- RED: `tests/unit/test_summarizer_calls_dao.py` for migration presence, schema columns, record_call/count_in_window happy paths, success-only vs include-failures counting, time-window cutoff, index existence.
- RED: `tests/unit/test_summarizer_sqlite_rate_limit.py` for cross-instance budget sharing, blocking at budget, success vs failure logging, get_summarizer wrapper selection, DAO-failure degrade-open.
- RED: `tests/unit/test_citation_routes.py` for invalid-kind 400, invalid-id 400, 200 round-trip per kind, 404 on missing, per-task observation list ordering and empty-task-id 400.
- GREEN: new DAO module, new wrapper class, new citation module, dashboard branches in `do_GET`, migration v14 in `engine/db.py`.
- REFACTOR: tag the SQLite limiter wrapper with `provider_name` so the in-memory limiter exposes the same attribute (matches the citation route pattern; useful when insights later joins by provider).

**Files**

- `src/superharness/engine/db.py` (CURRENT_SCHEMA_VERSION 13 → 14, `_migration_v14` added)
- `src/superharness/engine/summarizer_calls.py` (new DAO)
- `src/superharness/engine/summarizer.py` (`_SQLiteRateLimitedSummarizer`, `get_summarizer(project_dir=)`)
- `src/superharness/engine/observation_capture.py` (`project_dir` kwarg threaded through)
- `src/superharness/engine/state_writer.py` (pass `project_dir` to capture)
- `src/superharness/commands/citation.py` (new)
- `src/superharness/scripts/dashboard-ui.py` (four new route branches)
- `tests/unit/test_summarizer_calls_dao.py` (new)
- `tests/unit/test_summarizer_sqlite_rate_limit.py` (new)
- `tests/unit/test_citation_routes.py` (new)

**Explicitly out of scope**

- Token usage capture from real provider responses. The DAO has the columns; providers return strings only today. Wiring usage extraction is one follow-up; emitting it via `shux insights` is another.
- HTML rendering of citations on task pages. Operators can curl the new JSON routes. HTML cards are the next sensible UI iteration once the data shape settles.
- A `shux observation list <task-id>` CLI to mirror the route. Add when the auto-capture loop has produced enough rows to make a CLI list useful.
- `shux insights` extension for summarizer spend. Wire when the operator wants spend visibility.

## Iteration 9: claude-code summarizer + CLI provider DRY-up

**Motivation**

Operator already pays for Claude Max and uses a DeepSeek-routed OpenCode setup; neither has a separate API key sitting in env. Both OpenCode and Claude Code expose a subprocess interface that inherits whatever auth the local CLI is configured with. Add a `claude-code` summarizer alongside `opencode` so the operator can flip between them without provisioning HTTP credentials.

**Acceptance criteria**

1. Extract `_CLISummarizer` base class from the existing `OpenCodeSummarizer`. Behaviour-preserving refactor.
2. New `ClaudeCodeSummarizer(_CLISummarizer)` with `DEFAULT_BINARY="claude"` and `DEFAULT_SUBCOMMAND=("-p",)`. Reuses Claude Max OAuth or `ANTHROPIC_API_KEY`, whichever the local `claude` CLI is set up for.
3. Registered as `claude-code` with `max_per_hour=30` (same as opencode, both subprocess-based).
4. Existing `OpenCodeSummarizer` tests stay GREEN (regression coverage for the refactor).
5. New smoke test mirrors the existing opencode entry; skips when `claude` binary is missing.

**TDD**

- RED: `tests/unit/test_claude_code_summarizer.py` for binary-missing refusal, round-trip via mocked subprocess, ANSI strip, private-tag strip, non-zero exit raises, timeout raises, `--model` flag pass-through, registry lookup under `claude-code`, custom subcommand override. Plus one regression test asserting OpenCodeSummarizer behaviour is unchanged after the base extraction.
- GREEN: subclass `OpenCodeSummarizer` and `ClaudeCodeSummarizer` from the new `_CLISummarizer` base; register the new name.
- REFACTOR: shared `_build_prompt` and `_ANSI_RE` already at module level from iter 7. The base class wraps `subprocess.run`; subclasses only set defaults.

**Files**

- `src/superharness/engine/summarizer_providers.py` (`_CLISummarizer` base, `ClaudeCodeSummarizer`, registry entry)
- `tests/unit/test_claude_code_summarizer.py` (new)
- `tests/integration/test_summarizer_smoke.py` (new claude-code smoke entry)

**Usage**

```bash
# Option B (default for operator): cheap, uses DeepSeek via opencode auth
export SUPERHARNESS_SUMMARIZER=opencode

# Option A (later): real Claude summaries via Max plan OAuth
export SUPERHARNESS_SUMMARIZER=claude-code
```

Flip per-shell, per-project, or per-process. The auto-capture loop honours the env var on every transition.

**Explicitly out of scope**

- A `~/.superharness/.env` loader so the env var persists across shells. Operator can set it in their shell rc file or per-project `direnv`.
- Real OAuth-token extraction from macOS keychain (claude-mem pattern). The CLI subprocess inherits that auth automatically, so direct keychain access is unnecessary.
- Output-format flags for `claude` (e.g. `--output-format json`). Default text mode is fine for short summaries; tune via `subcommand` kwarg if needed.

## Iteration 10: dashboard HTML for observations and citations

**Motivation**

The iter-8 JSON routes expose observation snapshots and the four citation kinds (observation, handoff, decision, failure), but the dashboard at `:8787` has no UI surface for them. Operator has to curl. Add an Observations panel that renders one card per snapshot, and a Citation panel that opens when a reference link is clicked. Together they make the dashboard a full audit trail without leaving the browser.

**Acceptance criteria**

1. New `#observationsCard` panel in `dashboard.html` with sticky header, close button, copy button, meta line, body.
2. New `#citationCard` panel for showing a single handoff/decision/failure row.
3. New "Observations" button on the existing task-report card header. Clicking it pulls the task id from the report meta line and calls `loadObservations(taskId)`.
4. `loadObservations(taskId)` fetches `/api/task/<id>/observations` and renders one card per row with `#id · phase · created_at` header and the summary text.
5. Citation links inside summaries (`observation/42`, `handoff/17`, `decision/8`, `failure/3`) are auto-detected and linkified. Clicking opens `#citationCard` populated from the matching sibling route.
6. HTML escape on the summary before regex linkification so injected anchors are safe.
7. No new Python tests required for browser behaviour. A markup-presence test (`tests/unit/test_dashboard_observation_card_markup.py`) catches accidental deletion of IDs and entry points.

**Files**

- `src/superharness/scripts/dashboard.html` (new cards + JS functions)
- `tests/unit/test_dashboard_observation_card_markup.py` (new, 8 assertions on template content)

**Explicitly out of scope**

- A standalone observations route on the dashboard nav. The entry point is contextual via the task-report card.
- Markdown rendering inside summary cards. Plain-text plus citation linkification is sufficient.
- Editing or deleting observation rows from the dashboard. They are append-only by design.

## Iteration 11: token usage capture from HTTP providers + insights section

**Motivation**

`summarizer_calls` has `input_tokens` and `output_tokens` columns since iter 8. Providers were not yet populating them. Wire each HTTP provider to extract usage from its response shape; surface the totals via `shux insights`. CLI providers (opencode, claude-code) have no token info in stdout so their rows record NULL.

**Acceptance criteria**

1. Each HTTP provider sets `self.last_usage = {"model", "input_tokens", "output_tokens"}` after a successful response. Shapes per provider:
   - Anthropic: `payload["usage"]["input_tokens"]` / `payload["usage"]["output_tokens"]`
   - Gemini: `payload["usageMetadata"]["promptTokenCount"]` / `payload["usageMetadata"]["candidatesTokenCount"]`
   - OpenAI-compatible (OpenAI + OpenRouter): `payload["usage"]["prompt_tokens"]` / `payload["usage"]["completion_tokens"]`
2. Missing usage block defaults to None token values; the limiter logs NULL.
3. `_SQLiteRateLimitedSummarizer._log` reads `getattr(inner, "last_usage", {})` and passes `model`, `input_tokens`, `output_tokens` to `record_call`.
4. CLI provider rows are recorded with NULL token columns (no extraction from stdout).
5. New `_summarizer_breakdown(conn)` in `engine/insights.py` returns `[{provider, calls, successes, failures, input_tokens, output_tokens}]` ordered by call count. Empty when the `summarizer_calls` table is missing.
6. `get_insights()` returns the new `summarizer` key.
7. `shux insights` (in `commands/insights.py`) renders a `── summarizer ──` section with per-provider counts and `in=N out=M` token totals (or `tokens=n/a` when both zero).

**TDD**

- RED: `tests/unit/test_summarizer_token_usage.py` for each provider's usage extraction (mocked transport), missing-usage fallback, SQLite limiter recording the tokens end-to-end, CLI provider NULL columns.
- RED: `tests/unit/test_insights_summarizer_section.py` for empty section, per-provider aggregation, ordering by call count, missing-DB graceful return, CLI rendering of the new section.

**Files**

- `src/superharness/engine/summarizer_providers.py` (Anthropic, Gemini, ChatCompletions: set `self.last_usage`)
- `src/superharness/engine/summarizer.py` (`_SQLiteRateLimitedSummarizer._log` accepts model/tokens, reads from inner's `last_usage`)
- `src/superharness/engine/insights.py` (new `_summarizer_breakdown` helper, key added to result)
- `src/superharness/commands/insights.py` (new `── summarizer ──` section in `_print_insights`)
- `tests/unit/test_summarizer_token_usage.py` (new)
- `tests/unit/test_insights_summarizer_section.py` (new)

**Explicitly out of scope**

- Cost-per-call dollar conversion (would require per-model rate tables). Tokens alone are enough; spend can be computed externally.
- Token extraction from CLI provider stdout (opencode/claude-code). Their formats are not stable; subprocess-based providers stay at NULL token columns. Operators who want spend visibility should switch to an HTTP provider for that period.
- A dashboard `/api/insights/summarizer` route. CLI is the surface; the dashboard already shows a `budget` block via its own snapshot pipeline.

## Iterations explicitly deferred (from the CONCEPT doc)

- Observation snapshot auto-capture on `report_ready` transition (item 1 of the CONCEPT). Needs a summarizer adapter interface and provider-key handling. Lands once the storage layer is in production use.
- Live event stream to messaging channels (item 5).
- Adapter contracts for Gemini CLI, OpenCode, Cursor (item 6).
- Semantic recall (item 7).
- Token-cost annotations (item 8).

## Verification

- Each iteration runs `pytest tests/unit/test_<name>.py -q` GREEN before moving on.
- Full unit-test suite stays GREEN at the end. Pre-existing CI failures noted in HANDOFF.md remain pre-existing (not addressed here).
- No new external dependencies. No new outbound network calls. SQLite stays the sole source of truth.
- No version bump in this branch.
