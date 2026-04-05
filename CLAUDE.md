# superharness

## Identity
Read `SOUL.md` for operating constraints, guardrails, and identity context.

# Identity Core — Project Owner

Project owner context. Keep personal/company details out of committed files.

## Operating constraints
- Limited weekly bandwidth.
- Ship > plan. One task per session.

## Guardrails
- Read CLAUDE.md or AGENTS.md before starting work.
- Never edit `.env`, credentials, or secrets.
- Never push directly to `main`.
- Run required checks before handoff/commit.

---
See also: `SOUL.md.template` for the separate soul file approach (preferred for new projects).


## This Project
- What: superharness
- Stack: Python (primary), shell scripts
- Status: active

## Commands
- **Install (dev):** `pip install -e .`
- **Test:** `pytest tests/ -q`
- **Lint/scan:** `shipguard scan .`
- **Run CLI:** `superharness <cmd>` or via `shux <cmd>`

## Before Starting Work
- Run `superharness recall --project . "KEYWORDS"` with terms related to your task
- Check for prior decisions, failures, or context from earlier sessions

## Cross-Agent Protocol
- Read `.superharness/contract.yaml` before starting work.
- Read `.superharness/failures.yaml` and `.superharness/decisions.yaml`.
- Read handoffs addressed to `claude-code`.
- Keep task status, ledger, and handoff updated before stopping.
- Keep task `project_path` absolute and accurate.

## Vault Backlog Rule
When writing anything to the Obsidian vault, also check and update `notes/0_meta/backlog/_backlog_index.md`:
- Append any new actionable items (TODOs, ideas, "next steps") under the appropriate project heading.
- Do not duplicate items already present.
- Use format: `- [ ] **project: idea** — description`
- `shux hygiene` checks that the backlog index exists.

## Task Scope Rule
If a task has **>3 acceptance criteria** or the plan touches **>4 files**, decompose it into subtasks before approving:
1. Split into subtasks with `blocked_by` for ordering
2. Each subtask should be completable in <10 min of agent time
3. Use `shux delegate <id> --orchestrate` for auto-decomposition, or split manually
4. The plan approval flow will warn when a task exceeds the threshold

This is enforced by a scope warning on `plan_approved` transitions.

## CHANGELOG Policy (Strict)
- `CHANGELOG.md` is append-only.
- Never edit, reorder, or delete existing lines in `CHANGELOG.md`.
- Add new entries at EOF only.
- For corrections, append a new correction entry (do not rewrite history).
- Before commit, run: `bash /path/to/superharness/scripts/check-changelog-append-only.sh --staged`.

Reference: `superharness/protocol/spec.md`.
