# superharness — Codex Rules

## Project Description
superharness coordinates Claude Code and Codex CLI through contract/handoff/inbox protocols.

## Core Rule
- Follow cross-agent protocol lifecycle in `.superharness/*` files.

## CHANGELOG Policy (Strict)
- `CHANGELOG.md` is append-only.
- Never edit, reorder, or delete existing lines in `CHANGELOG.md`.
- Add new entries at EOF only.
- For corrections, append a new correction entry (do not rewrite history).
- Before commit, run: `bash scripts/check-changelog-append-only.sh --staged`.
