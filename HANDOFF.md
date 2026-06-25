# Handoff — superharness

> Latest: 2026-05-27, 3 bug reports from nemorad session + v1.68.0 fixes
> Previous: 2026-05-26, discussion engine overhaul + agent availability (v1.66.0 live, PR #292)
> PyPI latest: **v1.68.0** (released)

## 2026-05-27 session: 3 bugs found during nemorad integration

### Bugs reported (with root cause + fix)

| Bug | Doc | Severity | Fixed in |
|-----|-----|:---:|:---:|
| Watcher dies between sessions | `docs/bugs/watcher-dies-between-sessions.md` | HIGH | v1.68.0 (operator daemonize) |
| Gemini CLI silent failure in discussion | `docs/bugs/gemini-discussion-dispatch-silent-failure.md` | MEDIUM | v1.68.0 (orphan recovery) |
| `--tier max` ignored for discussions | `docs/bugs/discussion-dispatch-tier-ignored-double-failure.md` | HIGH | NOT YET (wiring needed) |

### Watcher death root cause

`shux operator start` runs `monitor_and_recover()` as a foreground blocking call. When the invoking shell (bash tool) terminates, the process tree dies. Fix: `shux operator install` creates launchd plist with KeepAlive.

### Discussion dispatch issues (2 failures in one session)

1. **`--tier max` silently ignored** — `_prepare_launch_context` hardcodes `claude-sonnet-4-6` for discussions. The `--tier` CLI flag is never consumed by the discussion dispatch code path.

2. **Silent dispatch failures** — Both claude-code and opencode dispatched at 19:38 UTC, both failed, zero round files, zero error logs, zero retry attempts. Likely Anthropic API evening degradation + no retry logic for discussion rounds.

3. **Orphan dispatch during operator cycling** — v1.68.0 added orphan recovery for inbox items, but discussion round retries still go straight to `failed_participant`.

### What's still needed (not yet in any release)

- Wire `--tier` flag into `_prepare_launch_context` via `model_routing.resolve_model()`
- Capture agent stderr on discussion round failure
- Add retry (at least 1x) for discussion round dispatch failures
- Dispatch heartbeat for long-running rounds

---

## 2026-05-26 session: discussion engine + consensus + agent availability

### What shipped (v1.66.0, PR #292)

**Discussion engine:** orchestrator skip for rounds, stronger prompt, verdict normalization (word-boundary regex), consensus threshold max(2,n-1), disk file scanning, no-engagement timeout.

**Agent availability:** binary + rate-limit + daemon heartbeat checks before dispatch, heartbeat auto-registration on delegate, daemon-dead GC detection.

**Other:** notify --message, --print-only no longer hangs, retry_count + failed_reason preserved, retry-alert fires at exhausted.

**Tests:** 20+ new (consensus threshold, verdict normalization, disk detection, heartbeat registration, round completion).

**Discussions run:** 6 attempts today, root cause found: agents complete inbox items but don't always create submission files. Fixed by disk scanning + stronger prompt + verdict normalization.

### Where to pick up

1. Start fresh discussion with all fixes — should work end-to-end
2. Observability metrics engine from docs/observability-spec-d2.md
3. Ship SKILL_GENERICITY_REVIEW.md to Claude

---

## 2026-05-25 session: production hardening — 16 bugs, 900+ tests, orchestrator, GC

### What shipped

**Orchestrator auto-dispatch:**
- Orchestrator now default path (`RoutingPlan`, `route()`). Decides owner+tier+effort+decompose.
- `--no-orchestrate` flag skips. `--print-only` skips both orchestrator + auto-classify (no more hangs).
- Fallback routing when all models fail. Consensus pipeline: discussion → extract action items → tasks (plan_proposed → operator approval required).

**Model updates:**
- All 4 owner max-tier models: claude=Opus 4.7, codex=GPT-5.5, gemini=Gemini 3.1 Pro, opencode=DeepSeek V4 Pro
- Standard/mini tiers updated across all agents. `supports_effort` on all manifests.
- Orchestrator chain includes all 4 owners with correct model IDs.

**GC overhaul (7 gaps + no-engagement timeout):**
- Duplicate inbox merge, zombie running+pending detection, discussion deadlock auto-close (>30min)
- Orphaned discussion inbox cleanup, stuck waiting_input auto-archive (10,210 cleaned)
- Time-based GC (every 60s), no-engagement timeout (0 submissions after 30min → failed_participant)
- `retry_count` now increments via `_retry_agent` (preserves row identity + failed_reason)
- Retry-alert fires at exhausted (rc >= max_rc), not at rc >= 3 (false positives fixed)

**Bug fixes (16 total):**
1. Retry creates new rows → retry_count=0 forever → `_retry_agent`
2. Discussion rounds stuck → lifecycle gate blocks multi-agent → skip waiting_input for /round- tasks
3. Participant floor minimum reflex → `max(2, available-1)` + warning
4. NULL metadata crashes handoffs → `_row_to_handoff` handles None
5. Effort silently ignored → manifests declare `supports_effort`
6. Duplicate inbox → `_gc_duplicate_inbox`
7. Stale waiting_input → `_gc_stuck_waiting_input`
8. No-engagement timeout → GC closes 0-round discussions after 30min
9. Retry-alert false positive → exhausted check
10. Agent availability gate → binary + rate-limit + daemon heartbeat
11. --print-only hangs → skip orchestrator + auto-classify
12. YAML write paths → SQLite-first, YAML export-only
13. Already-submitted re-dispatch → defense-in-depth is_submitted check
14. Agents without daemons enqueued → heartbeat check in `_agent_available`
15. Watcher dead → `discuss start` warns if watcher missing
16. API key in status → removed, replaced with daemon heartbeat check

**Discussions ran (3):**
| ID | Topic | Outcome |
|----|-------|---------|
| `...114727Z` | Review production readiness | Deadlocked (bug found + fixed) |
| `...123734Z` | Self-learning architecture | No engagement → auto-closed |
| `...131328Z` | GC improvement | Consensus reached, task auto-created |

**Testing (900+ new):**
- Smoke: 299 | State machine: 306 | Contract: 122 | Integration: 110 | GC: 24 | Chaos: 14 | E2E: 5 | Perf: 2
- `docs/TEST_STRATEGY.md` — mandatory CI gates with current counts
- State machine: all 54 legal + 220+ illegal transitions tested
- Contract: manifest structure, model resolution, orchestrator chain, launcher scripts
- Vault `notes/tests/Testing Strategy.md` updated with overlay template + superharness case study

**Backlog completed:**
- Observability spec (`docs/observability-spec-d2.md`): metrics table, dashboard API, KPIs, alert thresholds
- Agent health: `/api/health` dashboard endpoint, daemon heartbeat in status
- E2E tests: 5 passing (task lifecycle, doctor, status, contract, discussion)
- Self-learning pipeline: consensus extracts per-agent action items as `plan_proposed` tasks
- Performance benchmarks: inbox query <100ms, status count <50ms

**Vidistiller integration:**
- SSH tunnel: `localhost:8000` → vidistiller VM (`10.255.181.20`)
- API key configured. Submit video URLs → get transcripts via `/api/jobs`.

### Where to pick up

1. **Build the observability metrics engine** from `docs/observability-spec-d2.md` — add `learning_metrics` table, capture on task completion
2. **Wire orchestrator subtask dispatch** — `_record_decomposition` creates subtasks but doesn't enqueue them
3. **More integration tests** — discussion round advance, orchestrator decomposition, state machine timeouts
4. **Watcher health check in all discussion projects** — scalping_bot, synod, semblar


---

## 2026-05-18 session: state isolation — XDG path resolver, Iterations 1-4

### What landed

Four TDD iterations on branch `feat/paths-resolver` (4 commits, not yet pushed or PRed).
State.db now moves out of the repo dir for new projects. Existing projects keep working unchanged via fallback.

| Iter | What | Files | Tests added |
|------|------|-------|-------------|
| 1 | `resolve_state_dir`, `resolve_config_dir`, `project_hash` added to `utils/paths.py` | `utils/paths.py` | 5 |
| 2 | `resolve_xdg_state_db_path(project_path)` — composed function for full out-of-repo db path | `utils/paths.py` | 3 |
| 3 | `mcp/session.py init_session` prefers XDG path, falls back to legacy `.superharness/state.sqlite3` | `mcp/session.py` | 2 |
| 4 | `engine/db.py get_connection` prefers XDG path, creates there for new projects | `engine/db.py` | 3 + `test_db_file_created` updated |

All pure additive changes. Zero regressions. Full unit suite: 2911 passed, 543 skipped, 0 failed (confirmed twice).

### Path resolution contract (now in effect)

```
XDG default: ~/.local/state/superharness/<12-char-sha256-of-project-path>/state.db
Env override: SUPERHARNESS_STATE_DIR/<hash>/state.db
Legacy fallback: <project_dir>/.superharness/state.sqlite3
```

Decision order (both `init_session` and `get_connection`):
1. XDG path exists → use it
2. Legacy path exists → use it (existing projects, zero migration needed)
3. Neither exists → create at XDG (new projects never write into the repo)

### Config dir (not yet wired into consumers)

`resolve_config_dir()` returns `~/.config/superharness` (XDG_CONFIG_HOME) or `SUPERHARNESS_CONFIG_DIR` override. The credentials path the gateway already uses (`~/.config/superharness/credentials.env`) is consistent with this — no migration needed there.

### What is NOT done yet (next iterations)

- `engine/state_reader.py` — 10+ call sites of `get_connection` pass `project_dir`; they will automatically benefit from iter 4, but callers that hard-build the legacy path directly (grep for `.superharness/state.sqlite3` in state_reader.py) still need updating.
- `engine/db.py _backup_db()` — still hardcodes legacy path for pre-migration backups; harmless but should migrate to XDG.
- `shux init` scaffold — currently writes `.superharness/profile.yaml` etc. into the project dir. When state.db is XDG-only, the init flow should not create a `.superharness/` directory for state purposes (though config files like `profile.yaml` may legitimately live there).
- Migration CLI (`shux migrate-state`) — help existing projects move legacy state.db to XDG voluntarily.
- `engine/state_reader.py` functions that call `os.path.exists(os.path.join(project_dir, ".superharness", "state.sqlite3"))` for readiness checks need to check both paths.

### Branch state

`feat/paths-resolver`, 4 commits ahead of main. **Not pushed.** No version bump (no release per `NO RELEASE` policy).

Next step: `git push -u origin feat/paths-resolver && gh pr create` then continue with Iteration 5 (state_reader.py readiness check migration) or the migration CLI.

### Context

Design doc (full 13-iteration plan) is on PR #255 (`docs/notify-design-and-instruction-sync`, open, not merged). That branch has `docs/CONCEPT-notifications-and-state-isolation.md`. The plan-iter output from the 2026-05-18 session was inline only — save it as `docs/PLAN-notifications-and-state-isolation.md` if needed for the next session.

PR #255 also contains the instruction-file sync (AGENTS.md / CLAUDE.md / GEMINI.md) with the Strict Installation Decoupling clause. Merge it when ready.

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
`bash src/superharness/adapters/claude-code/hooks/<hook>.sh`
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
