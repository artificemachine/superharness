# superharness

## Identity
Read `SOUL.md` for operating constraints, guardrails, and identity context.

You are working for the project owner. Ship > plan. One task per session.

## This Project
- What: superharness — multi-agent session handoff framework for Claude Code, Codex CLI, Gemini CLI
- Stack: Python 3.11+ (click CLI, pydantic v2), shell scripts (bash), SQLite (state backend)
- Tests: 2.5k tests (pytest), run with `uv run pytest tests/ -q`
- Entrypoint: `src/superharness/cli.py` → routes to `src/superharness/commands/*.py`

## Dev Commands

```bash
uv run pytest tests/ -q                # full suite (~5 min); takes --tb=short -x for fast-fail
uv run pytest tests/unit/ -q           # unit tests only (~4 sec)
uv run pytest tests/test_smoke.py      # minimum smoke test
uv run python -m superharness demo     # zero-config walkthrough
```

The full suite has 4 pre-existing failures (dashboard-port detection — ignores these).

## Project Rules
Run `shux rules` to list all project constraints. Rules in `.superharness/rules/` are
the authoritative source for policies, conventions, and architecture facts.
When you need to know how something works or what's allowed, check rules first.

Key rules (full list via `shux rules`):
- `state-backend` — SQLite is SoT; contract/inbox/failures/decisions YAML are DEAD
- `discussion-state` — discussions live in SQLite, not YAML files
- `changelog-policy` — CHANGELOG.md is append-only
- `branch-policy` — never merge to main without owner approval
- `task-scope` — decompose tasks >3 criteria or >4 files

## State Backend: SQLite (post-YAML migration)

As of v1.41+, all project state lives in `.superharness/state.sqlite3`. YAML files
(`contract.yaml`, `inbox.yaml`, etc.) are NO LONGER the source of truth.

**When you need task/state data, use the CLI — never read YAML directly:**
- `shux contract` — view all tasks
- `shux context <task-id>` — full task context (handoffs, failures, decisions, ledger)
- `shux status` — dashboard summary
- `shux recall <keywords>` — search past handoffs

The dual-write parity system (`parity.py`, `yaml_sync.py`, `heal_parity.py`) has been
deprecated. The modules exist as no-op stubs during the transition.

`shux export-yaml --all` generates human-readable YAML snapshots from SQLite
for backup or inspection.

## Architecture (what an agent actually touches)

```
cli.py                → Click CLI, routes to commands/
commands/             → one file per CLI command (task, delegate, inbox_watch, etc.)
engine/next_action.py → pure state machine (16 task statuses, legal transitions)
engine/schemas.py     → Pydantic v2 models (TaskStatus, InboxStatus, etc.)
engine/contract_io.py → canonical contract write path (SQLite, atomic tempfile)
engine/state_writer.py→ set_task_status / set_inbox_status
engine/state_reader.py→ read API (always SQLite)
engine/lifecycle_rules.py → data-driven timeout rules table
engine/operator.py    → guardian: spawns watcher + dashboard, restarts on crash
engine/failure_classifier.py → classifies dispatch errors (retryable vs permanent)
engine/orchestrator.py → Opus-level task decomposition into subtasks
engine/*_dao.py (6)   → SQLite data access (tasks, inbox, handoffs, etc.)
engine/models.yaml    → model pricing and tier mapping per agent
scripts/dashboard-ui.py → HTTP server + browser dashboard (3.1k LOC — monolith)
adapters/             → Claude Code hooks, Codex CLI templates
adapter_manifests/    → agent YAML manifests (capabilities, model tiers, launchers)
```

## CHANGELOG Policy (Strict)

- `CHANGELOG.md` is **append-only** — enforced by `.githooks/pre-commit`.
- Never edit, reorder, or delete existing lines. Add new entries at EOF only.
- Corrections append a new correction entry (never rewrite history).
- Pre-commit runs `check-changelog-append-only.sh --staged` and `check-shell-entrypoints.sh`.

## Task Scope Rule

If a task has **>3 acceptance criteria** or touches **>4 files**, decompose into subtasks:
- Use `shux delegate <id> --orchestrate` for auto-decomposition
- Each subtask should be completable in <10 min of agent time

## Before Starting Work

- `shux recall --project . "KEYWORDS"` — search past handoffs and ledger
- `shux contract` — check current tasks and statuses
- `shux context <id>` — full context for a specific task

## Verification Policy

- Before closing a task, run end-to-end verification (not unit tests alone).
- `shux verify --id <id> --method "<how>" --result pass` records the result.
- `shux close <id>` rejects unverified tasks; use `--skip-verify` only for typos/config-only.

## Branch and Release Policy

- **Never merge to `main` or push without explicit owner instruction.**
- **⛔ NO RELEASE** — no version tags, PyPI publish, or `/ship-release` without owner approval.
- Work on feature branches (`feat/...`, `fix/...`, `chore/...`).
- Cross-repo morpheme link is RETIRED (v1.24.2). Schema v1.1 ships on PyPI.

## Test Quirks

- Some tests need a SQLite DB in `.superharness/` — use test fixtures in `tests/fixtures/`.
- Dashboard port-detection tests fail when no dashboard is running (pre-existing, safe to ignore).
- Use `uv` for running Python: `uv run pytest`, `uv run python -m superharness`.

## Self-Improvement Health Check

Every 3-5 sessions or when starting a new task, verify the self-learning systems are alive:

```bash
shux profile show                          # behavioral profile — should have data
shux memory-roots list                     # global memory scan roots — should be configured
shux daemon status                         # watcher/daemon — should be running

# Deep check:
ls ~/.config/superharness/behavioral/      # profile files — should exist
ls ~/.config/superharness/memory/          # global memory — should have entries
cat .superharness/memory/pitfalls.md       # project learnings
```

If any system is empty or down, report it to the operator with: what's missing, what should be there, and the fix command (e.g. `shux daemon start`).
