# superharness — Roadmap

## Recently Shipped

| Feature | Version | Description |
|---------|---------|-------------|
| `shux onboard` | v1.10.0 | 7-step setup wizard (detect, init, git_track, doctor, task, delegate, summary) |
| AGENTS.md auto-creation | v1.10.0 | `shux onboard` writes AGENTS.md if missing |
| Global CLAUDE.md append | v1.10.2 | `shux onboard` appends superharness section to `~/.claude/CLAUDE.md` once per machine |
| Cold-start banner | v1.10.1 | `shux --help` in projects without `.superharness/` shows a quickstart pointing to `shux onboard` |
| Step hint lines | v1.10.1 | Each `shux onboard` step prints a `→` explanation line |
| `shux config get/set` | v1.10.0 | Dot-path read/write for `profile.yaml` keys |
| `shux benchmark --models` | v1.10.0 | 7-day per-model cost breakdown table |
| Budget guard in `delegate` | v1.10.0 | WARN at 80%, BLOCK at 100% of `budget.daily_limit` |
| `shux delegate --force` | v1.10.0 | Bypass budget BLOCK |
| `budget.daily_limit` / `budget.weekly_limit` | v1.10.0 | Profile.yaml budget config keys |

## In Progress

See `docs/plan-module-system.md` for the active module system plan (12 iterations).

## Planned: always-on-agent Merge

Merge `always-on-agent` (~1800 LOC) into superharness. The module system makes this possible — each always-on-agent feature maps to an existing module or a new one.

### What overlaps (already in superharness)

| always-on-agent | superharness | Notes |
|----------------|-------------|-------|
| Serial runner | Watcher dispatcher | Same concept, superharness is more mature |
| Heartbeat + exclude windows | `watcher.heartbeat` | Merge exclude windows only |
| ntfy notifications | `ntfy` module | Template exists, wire in notifier.py |
| Web dashboard | Monitor UI | Superharness UI is richer |
| Session persistence | Handoff protocol | Already handles this |

### What's unique (must port)

| Feature | Source file | LOC | Value |
|---------|-----------|-----|-------|
| Cron parser | `cron.py` | 136 | Markdown job files with YAML frontmatter, zero-dep cron expression parser |
| Telegram bridge | `bridges/telegram.py` | 160 | Zero-framework bot, poll-based, command routing |
| Discord bridge | `bridges/discord.py` | 215 | Gateway WebSocket, zero-framework |
| Daemon mode | `daemon.py` | 274 | Start/stop/status, PID file, foreground/background |
| Model fallback chain | `runner.py` | 195 | Try model A → fall back to B → budget guard |
| Config validation | `config.py` | 197 | YAML config with schema validation |

### TDD Iterations

```
0. Cron parser                          — 5 tests, 1 hr
   RED:  test_parse_cron_expression, test_next_fire_time,
         test_markdown_job_file, test_invalid_expression, test_matches_now
   GREEN: port cron.py → src/superharness/engine/cron.py
   REFACTOR: integrate with auto-schedule module (on_watcher_tick)

1. Telegram bridge                      — 4 tests, 2 hr
   RED:  test_poll_updates, test_command_routing,
         test_send_message, test_no_token_skips
   GREEN: port bridges/telegram.py → src/superharness/modules/actions/telegram.py
   REFACTOR: wire into telegram module template (on_close, on_delegate)

2. Discord bridge                       — 4 tests, 2 hr
   RED:  test_gateway_connect, test_message_handler,
         test_command_parse, test_no_token_skips
   GREEN: port bridges/discord.py → src/superharness/modules/actions/discord.py
   REFACTOR: create discord module template

3. Daemon mode (shux daemon)            — 5 tests, 2 hr
   RED:  test_start_creates_pid, test_stop_kills_pid,
         test_status_reports_running, test_double_start_noop,
         test_stop_when_not_running
   GREEN: port daemon.py → src/superharness/commands/daemon.py
   REFACTOR: add `shux daemon start|stop|status` to CLI

4. Model fallback chain                 — 3 tests, 1 hr
   RED:  test_fallback_on_failure, test_budget_guard,
         test_chain_respects_order
   GREEN: port runner.py fallback logic → src/superharness/engine/model_router.py
   REFACTOR: integrate with delegate model resolution

5. Heartbeat exclude windows            — 3 tests, 1 hr
   RED:  test_exclude_window_blocks, test_outside_window_runs,
         test_timezone_aware
   GREEN: port heartbeat.py exclude logic → existing watcher heartbeat
   REFACTOR: add exclude_windows to watcher config

6. Config validation                    — 3 tests, 1 hr
   RED:  test_valid_config_passes, test_missing_required_fails,
         test_unknown_key_warns
   GREEN: port config.py → src/superharness/engine/config_validator.py
   REFACTOR: wire into `shux doctor`
```

**Total:** ~27 tests, ~10 hr across 7 iterations.
**Build order:** 0 → 1 → 2 → 3 → 4 → 5 → 6 (sequential, each builds on prior)
**After merge:** archive `always-on-agent` and `celstnblacc/always-on-agent` on GitHub.

## Deferred

### Git Worktree Support (parallel agent isolation)

**Status:** Implemented in v1.7.0.

**What:** Each dispatched task runs in its own `git worktree`, so multiple agents can work on different tasks without conflicting on the working tree.

**Implementation (v1.7.0):**
- `engine/parallel_dispatch.py`: `fanout_dispatch()` creates N worktrees under `.superharness/worktrees/`, dispatches agents in parallel threads, collects diffs, cleans up via `try/finally`
- `engine/swarm.py`: `swarm_dispatch()` extends fan-out with an Opus reviewer phase that picks the best solution
- `.superharness/` is symlinked to each worktree (shared contract/inbox/ledger)
- `_sanitize_task_id()` prevents path traversal in branch names
- Worktree garbage collection runs automatically after dispatch; `shux hygiene` can also clean stale worktrees
