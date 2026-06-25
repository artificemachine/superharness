# Skill Genericity Review — 2026-05-26

**Location:** `docs/SKILL_GENERICITY_REVIEW.md`

## Context

67 Claude commands synced to OpenCode skills. 16 of them reference `superharness` or `shux`. Some are genuine tool bindings (must stay project-specific), others are generic patterns that happen to mention superharness as an example. The latter should be rewritten to be tool-agnostic so any project can use them.

## Rule

- **Tool binding** = calls a specific CLI (`shux`, `superharness`), reads a specific file format (contract.yaml), or assumes a specific project structure → keep project-specific
- **Pattern** = describes a methodology, process, or audit that could work with any tool → rewrite to be generic
- **Hybrid** = pattern that currently hardcodes a tool reference → replace the tool reference with a placeholder or generic instruction

## Skills to make generic

| Skill | Current issue | Fix |
|-------|--------------|-----|
| `plan-iter` | Already generic (test pyramid per iteration). Good as-is. | None |
| `threat-model` | References `.superharness/` paths, `shux discuss` | Replace with generic: "review the project's architecture docs and data flow. If the project has an ADR directory, start there." |
| `production-ready` | References `shux doctor`, specific file paths | Replace with generic: "run the project's test suite. Check CI config for required gates. Verify README quickstart works." |
| `orphan-guard` | Already adapted: "agent sessions (Claude Code, OpenCode, Codex)". Good. | None |
| `gauntlet` | References `shux` commands, superharness pipeline | Replace pipeline references with generic: "scan for security issues (use the project's SAST tool), model threats, review code, audit QA coverage." |
| `good-morning` | "scan all projects, read the vault" — vault path is user-specific | Replace vault path with "read the project's documentation and any knowledge base" |
| `backlog` | Reads superharness contract | Replace with generic: "review recent activity and documentation, update the project's task tracker with new actionable items" |
| `loop-monitor` | Monitors superharness watcher | This is genuinely superharness-specific. Keep. |
| `worktree` | Git worktree management — already generic | None |

## Skills to keep project-specific

| Skill | Why |
|-------|-----|
| `ship` | Uses `shux` commands. Tool binding. |
| `superharness-production-ready` | Explicitly for superharness. |
| `new-project` | Creates project with superharness scaffolding. |
| `loop-monitor` | Monitors superharness watcher daemon. |
| `html-report` | Superharness-specific report generation. |
| `tell` | References superharness context. Works generically too. |

## Priority

1. `production-ready` — most reusable across projects
2. `threat-model` — security pattern, no reason to bind to superharness
3. `gauntlet` — pipeline pattern
4. `backlog` — task tracking pattern

## Example rewrite: production-ready

Before:
```
Run shux doctor. Verify .superharness/contract.yaml exists.
```

After:
```
Run the project's health check command (e.g., `make check`, `npm test`, `pytest`).
Verify the project has a task tracker or issue board configured.
```
