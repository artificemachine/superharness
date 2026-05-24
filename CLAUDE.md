# superharness

## Identity
Read `SOUL.md` for operating constraints, guardrails, and identity context.

## Project Rules
Before starting any work, run `shux rules` to see all project constraints.
Key rules:
- State lives in SQLite — contract.yaml, inbox.yaml, failures.yaml, decisions.yaml are DEAD
- Discussions live in SQLite, not YAML files
- CHANGELOG.md is append-only
- Never merge to main without owner approval
- Decompose tasks >3 criteria or >4 files

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

## Problem Triage Rule (Strict)
When a task, discussion, or test problem surfaces:
1. **State what you observe** — one or two sentences describing the problem.
2. **Check auto-mode first** — can the watcher, reconciler, CI, or scheduled job resolve it without intervention? If yes, say so and wait.
3. **Propose action only if auto-mode has a gap** — then suggest the smallest intervention and wait for confirmation.

Never jump straight to "want me to dispatch / fix / re-run X?" without going through steps 1 and 2 first.

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
- Run `shux daemon status --project .` — if stopped, run `shux daemon start --project .` before any autonomous work

## Cross-Agent Protocol
- Run `shux contract` to see current tasks and statuses (reads from SQLite, not tombstone YAML).
- Run `shux recall --project . "KEYWORDS"` to search past handoffs, failures, and ledger.
- Run `shux context <task-id>` for full context (handoffs, failures, decisions, ledger).
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

## Release Policy

Releases are triggered by pushing a `v*` tag (via `/ship-release` or `git push --tags`), not by merging to `main`. A PR merge alone does not tag or publish. `publish.yml` fires on `release: published`; `release.yml` fires on `v*` tag push. Never use `git push --force` to main.

## CHANGELOG Policy (Strict)
- `CHANGELOG.md` is append-only.
- Never edit, reorder, or delete existing lines in `CHANGELOG.md`.
- Add new entries at EOF only.
- For corrections, append a new correction entry (do not rewrite history).
- Before commit, run: `bash /path/to/superharness/scripts/check-changelog-append-only.sh --staged`.

Reference: `superharness/protocol/spec.md`.

## Cross-Repo Branch Link — RETIRED (2026-04-16)

> The paired-branch convention is retired as of v1.24.2. See
> `docs/morpheme-branch-policy.md` → "Retirement note" for rationale.
>
> **TL;DR**: adapter-payload schema stabilised at v1.1 (shipping on PyPI).
> Superharness is the producer; Morpheme is a consumer. All superharness
> work now lands on `main` via normal feature branches. Morpheme pins a
> superharness version and upgrades like any other dependency.

Historical pairing (preserved for context):

| Repo | Branch | Purpose |
|------|--------|---------|
| `superharness` (this repo) | `feat/superharness-integration-morpheme` | `shux adapter-payload --json` command + spec |
| `artificemachine/morpheme` | `feat/superharness-integration-morpheme` | Adapter boundary, Phase 2 renderer work |

Spec: `docs/adapter-payload-spec.md`. Model mappings: `docs/adapter-models.md`.

Schema version: `1.0` — validated by `ADAPTER_SCHEMA_VERSION` in Morpheme's `adapter.js`.
## Runtime Environment
- Claude Code uses the **Claude Agent SDK** (Python) for autonomous dispatch.
- This allows bypassing permission prompts and inheriting session context (warm-start).
- For manual troubleshooting, use `shux delegate --via cli`.
- See `docs/CONCEPT-sdk-vs-cli.md` for details.

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
