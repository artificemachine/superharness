# superharness

## Identity
Read `SOUL.md` for operating constraints, guardrails, and identity context.

You are working for the project owner.
Constraints: limited bandwidth. Ship > plan.

## This Project
- What: superharness
- Stack: Python/Ruby
- Status: active

## Before Starting Work
- Run `superharness recall --project . "KEYWORDS"` with terms related to your task
- Check for prior decisions, failures, or context from earlier sessions

## Cross-Agent Protocol
- Read `.superharness/contract.yaml` before starting work.
- Read `.superharness/failures.yaml` and `.superharness/decisions.yaml`.
- Read handoffs addressed to `codex-cli`.
- Keep task status, ledger, and handoff updated before stopping.
- Keep task `project_path` absolute and accurate.

## Verification Policy
- Before closing a task, run end-to-end verification — not unit tests alone.
- For UI tasks, the dev server must be running during verification.
- Use `superharness verify --id <task-id> --method "<how>" --result pass` to record the result.
- `superharness close` will reject tasks that have not been verified.
- Use `--skip-verify` only for trivial tasks (typos, config-only changes).

## CHANGELOG Policy (Strict)
- `CHANGELOG.md` is append-only.
- Never edit, reorder, or delete existing lines in `CHANGELOG.md`.
- Add new entries at EOF only.
- For corrections, append a new correction entry (do not rewrite history).
- Before commit, run: `bash /path/to/superharness/scripts/check-changelog-append-only.sh --staged`.

Reference: `superharness/protocol/spec.md`.
