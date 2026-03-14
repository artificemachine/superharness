# superharness — Claude Rules

## Project Description
superharness is a multi-agent session handoff framework for Claude Code. It manages contracts, handoffs, and context between sessions via shell hooks and adapters.

## Project Type
Python CLI + engine (cross-platform: macOS, Linux, Windows). No build step.

## Package Structure
- `src/superharness/` — Python package (CLI router, engine modules)
- `src/superharness/engine/` — Python engine (contract, inbox, validate, discuss, discussion, yaml_helpers)

## Test Commands
```bash
pytest tests/
```

## Key Structure
- `adapters/claude-code/hooks/` — Claude Code session hooks (session-start.sh, etc.)
- `src/superharness/` — Python package source
- `tests/unit/` — Unit tests
- `tests/integration/` — Integration tests
- `tests/e2e/` — End-to-end tests
- `.superharness/` — Contract, handoffs, and protocol state in each initialized project

## Conventions
- Hook output must be valid JSON with `additionalContext` and `hookSpecificOutput` keys
- All shell scripts must be executable (`chmod +x`)
- Tests use `pytest` with fixtures in `conftest.py`

## Superharness Session Lifecycle (Required)
- Start of task: call `search_vault` (obsidian-semantic MCP) with the task topic **before** reading the contract or handoffs. Vault search surfaces architectural notes, past decisions, and domain knowledge stored in Obsidian that the contract files don't capture.
- Start of task: read `.superharness/contract.yaml`, `.superharness/failures.yaml`, `.superharness/decisions.yaml`, and relevant handoffs in `.superharness/handoffs/`.
- **Plan gate (all tasks):** Before implementing anything, check if the contract task has `plan_confirmed_at` set. If not, write a plan handoff (`status: plan_proposed`, `plan_gate: {required: true, confirmed_by_user: false}`) summarising what you intend to do, set the contract task status to `plan_proposed`, append the ledger, and **stop**. Do not implement until the user confirms the plan in the monitor-ui or via CLI.
- During task: keep work inside assigned contract scope; record important tradeoffs/choices in contract decisions.
- End of task: update contract task status, append one line to `.superharness/ledger.md`, and create/update a handoff YAML in `.superharness/handoffs/`. If vault notes informed the work, reference them in the handoff summary.
- If blocked/failure: log failure details in contract failures (and promote to `failures.yaml` when reusable).

## Operator Shortcuts (`shux` prefix)
All shux shortcuts are defined in `SHUX.md` (repo root) — agent-agnostic, single source of truth.
Read `shux/SHUX.md` for the full command reference and behavior rules.

## CHANGELOG Policy (Strict)
- `CHANGELOG.md` is append-only.
- Never edit, reorder, or delete existing lines in `CHANGELOG.md`.
- Add new entries at EOF only.
- For corrections, append a new correction entry (do not rewrite history).
- Before commit, run: `bash scripts/check-changelog-append-only.sh --staged`.
