---
title: "Handoff: Superharness Module System"
date: 2026-03-20
task: module-system
owner: claude-code
status: ready-to-start
plan: docs/plan-module-system.md
---

# Handoff: Superharness Module System

## Context

Superharness (v0.8.0) is a multi-agent task coordination tool. It tracks contracts, delegates tasks to Claude Code / Codex CLI, and manages handoffs between sessions.

The module system adds opt-in enhancements that hook into the task lifecycle (close, verify, continue, delegate, watcher tick). Users enable modules via `shux enhance enable <name>`.

## What exists already

- **Superharness core**: init, doctor, monitor, delegate, close, verify, watch, status — all working, 732 tests passing
- **Scheduling gates** (just added): `scheduled_after`, `due_by`, `depends_on` fields on tasks — tested, in delegate.py
- **Idempotency fixes** (just added): monitor, close, verify are all idempotent — tested
- **Monitor UI**: web dashboard at :8787 with task display, watcher health, heartbeat, logs
- **always-on-agent** (separate project at ~/DevOpsSec/always-on-agent/): daemon-mode Claude Code with cron, Telegram, Discord, heartbeat — 38 tests. Will merge into superharness later.

## The plan

Full plan with TDD iterations: **`docs/plan-module-system.md`**

Read that file first — it has the complete design, security rules, iteration details with RED/GREEN/REFACTOR steps, file structure, and execution order.

## Build order

```
0. Module loader (YAML → dataclass)           — 5 tests, 1 hr
1. Module runner (lifecycle hooks)             — 7 tests, 2 hr
2. Registry + shux enhance CLI                 — 8 tests, 2 hr
3. Obsidian module                             — 8 tests, 3 hr
4. Auto-schedule module                        — 5 tests, 2 hr
5. Security module (shipguard)                 — 4 tests, 2 hr
6. Remember module                             — 2 tests, 1 hr
7. ntfy module                                 — 3 tests, 1 hr
8. Ship module                                 — 3 tests, 1 hr
9-11. OpenClaw, Telegram, Doctor (defer)
```

## Key files to read before starting

| File | Why |
|------|-----|
| `docs/plan-module-system.md` | Full plan with TDD steps, security rules, architecture |
| `src/superharness/commands/close.py` | Where `on_close` hooks will be wired |
| `src/superharness/commands/verify.py` | Where `on_verify` hooks will be wired |
| `src/superharness/commands/inbox_watch.py` | Where `on_watcher_tick` hooks will be wired |
| `src/superharness/cli.py` | Where `shux enhance` command group will be added |
| `tests/unit/test_verify_and_close.py` | Pattern for writing command tests |
| `tests/unit/test_delegate.py` | Pattern for scheduling gate tests |
| `tests/unit/test_install_hooks.py` | Pattern for idempotency tests |

## Architecture decisions

1. **Modules are YAML files** in `.superharness/modules/` — not Python packages
2. **Templates ship with superharness** in `src/superharness/module_templates/`
3. **`shux enhance enable <name>`** copies template to project, runs auto-detection
4. **Lifecycle events**: `on_close`, `on_verify`, `on_continue`, `on_delegate`, `on_watcher_tick`
5. **Module failure never blocks core** — if a module crashes, log a warning, continue
6. **Auto-detection** — modules check for binaries, env vars, paths, MCP servers
7. **Three levels for Obsidian**: local handoffs (always) → vault write (if path found) → MCP write (if server running)

## Security rules (STRICT)

- No SSH keys, API keys, tokens, passwords in source/templates/tests
- No real IPs, hostnames, VM names, or infra details
- All secrets via `_env` suffix pattern (e.g., `token_env: TELEGRAM_BOT_TOKEN`)
- Placeholder values only in examples

## How to start

```bash
cd ~/DevOpsSec/superharness
python -m pytest tests/ -q          # verify 732+ tests pass
cat docs/plan-module-system.md      # read the plan
# Start Iteration 0: Module Loader
```

## How to verify

After each iteration:
```bash
python -m pytest tests/ -q          # all tests pass
shux doctor                         # no new failures
```

After Iteration 2 (foundation complete):
```bash
shux enhance                        # should list available modules
shux enhance enable obsidian        # should copy template
shux enhance disable obsidian       # should set enabled: false
```
