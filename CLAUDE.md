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
- `templates/` — Handoff/contract YAML templates

## Conventions
- Hook output must be valid JSON with `additionalContext` and `hookSpecificOutput` keys
- All shell scripts must be executable (`chmod +x`)
- Tests use `pytest` with fixtures in `conftest.py`
