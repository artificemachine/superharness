# superharness — Claude Rules

## Project Description
superharness is a multi-agent session handoff framework for Claude Code. It manages contracts, handoffs, and context between sessions via shell hooks and adapters.

## Project Type
Shell scripts + Python tests (no build step)

## Test Commands
```bash
pytest tests/
```

## Key Structure
- `adapters/claude-code/hooks/` — Claude Code session hooks (session-start.sh, etc.)
- `tests/unit/` — Unit tests for hooks
- `tests/integration/` — Integration tests
- `tests/e2e/` — End-to-end tests
- `.superharness/` — Contract, handoffs, and protocol state in each initialized project

## Conventions
- Hook output must be valid JSON with `additionalContext` and `hookSpecificOutput` keys
- All shell scripts must be executable (`chmod +x`)
- Tests use `pytest` with fixtures in `conftest.py`

## Superharness Session Lifecycle (Required)
- Start of task: read `.superharness/contract.yaml`, `.superharness/failures.yaml`, `.superharness/decisions.yaml`, and relevant handoffs in `.superharness/handoffs/`.
- **Plan gate (all tasks):** Before implementing anything, check if the contract task has `plan_confirmed_at` set. If not, write a plan handoff (`status: plan_proposed`, `plan_gate: {required: true, confirmed_by_user: false}`) summarising what you intend to do, set the contract task status to `plan_proposed`, append the ledger, and **stop**. Do not implement until the user confirms the plan in the monitor-ui or via CLI.
- During task: keep work inside assigned contract scope; record important tradeoffs/choices in contract decisions.
- End of task: update contract task status, append one line to `.superharness/ledger.md`, and create/update a handoff YAML in `.superharness/handoffs/`.
- If blocked/failure: log failure details in contract failures (and promote to `failures.yaml` when reusable).

## Operator Shortcuts (`shux` prefix)
All shortcuts use the `shux` prefix. Old long-form phrases still work but `shux` is canonical.

| Phrase | Action |
|--------|--------|
| `shux contract` | Read `contract.yaml`, render task table, suggest next task, offer to delegate cross-agent tasks |
| `shux continue` | Resume active contract and run the full session lifecycle automatically |
| `shux close <task_id>` | Mark task done, append ledger line, write handoff YAML, stop |
| `shux delegate <task_id>` | Create task (if missing) + enqueue in one step; never create without enqueueing |
| `shux init` | Run `superharness init --interactive --project .`; report current state if already initialized |
| `shux status` | Run `superharness status --project .` — dashboard: contract, tasks, watcher, profile |
| `shux doctor` | Run `superharness doctor --project .` — prereq + protocol health check |
| `shux recall <keywords>` | Run `superharness recall --project . --query "<keywords>"` — search past handoffs + ledger |
| `shux uninstall` | Run `superharness uninstall --project .` — remove watcher and system artifacts for this project |
| `shux hygiene` | Run `superharness hygiene --project .` — validate protocol compliance (contract, handoffs, ledger) |
| `shux monitor` | Run `superharness monitor-ui --project .` — open browser dashboard |
| `shux watch` | Run `superharness watch --foreground --project .` — start continuous watcher in foreground |
| `shux update` | 1) `git pull` in the superharness repo to get latest, 2) re-run `superharness init` on current project to refresh `CLAUDE.md`, `AGENTS.md`, and templates |

## CHANGELOG Policy (Strict)
- `CHANGELOG.md` is append-only.
- Never edit, reorder, or delete existing lines in `CHANGELOG.md`.
- Add new entries at EOF only.
- For corrections, append a new correction entry (do not rewrite history).
- Before commit, run: `bash scripts/check-changelog-append-only.sh --staged`.
