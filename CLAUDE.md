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
- During task: keep work inside assigned contract scope; record important tradeoffs/choices in contract decisions.
- End of task: update contract task status, append one line to `.superharness/ledger.md`, and create/update a handoff YAML in `.superharness/handoffs/`.
- If blocked/failure: log failure details in contract failures (and promote to `failures.yaml` when reusable).

## Operator Shortcuts
- `contract today`: read `.superharness/contract.yaml` and list all tasks with id, status, owner, and suggest the next task to work on.
- `continue contract`: resume the active contract and execute the full lifecycle above automatically.
- `close task <task_id>`: mark task status, append ledger, and write handoff before stopping.
- `delegate <task_id>`: create contract task (if not exists) and enqueue it immediately for the watcher to dispatch. Always create + enqueue in one step — never create without enqueueing.

## CHANGELOG Policy (Strict)
- `CHANGELOG.md` is append-only.
- Never edit, reorder, or delete existing lines in `CHANGELOG.md`.
- Add new entries at EOF only.
- For corrections, append a new correction entry (do not rewrite history).
- Before commit, run: `bash scripts/check-changelog-append-only.sh --staged`.
