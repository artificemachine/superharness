# Spec decomposition for superharness

Six specifications were too few for this project. The realistic count is about 15 to 16.

Basis: 112 modules in `engine/`, 77 commands, the `guard/`, `mcp/`, `modules/` and `adapters/` areas, and the background services described in `docs/ARCHITECTURE.md`. The right unit is one spec per bounded contract, meaning a boundary with its own invariants. It is neither one spec per module nor one per command.

## Proposed breakdown

| ID | Contract |
|---|---|
| 001 | Foundation (failure reporting, CHANGELOG, no YAML state) |
| 002 | SQLite state store, migrations, `state_reader`/`state_writer` |
| 003 | Typed write boundaries, content-addressed context |
| 004 | Task lifecycle state machine and gates (`next_action`, `lifecycle_rules`) |
| 005 | Delegation, dispatch, worktree isolation |
| 006 | Model resolution (runtime bindings, fallback, budget) |
| 007 | Adapters and harness manifests |
| 008 | Handoffs and inbox |
| 009 | Discussions and consensus |
| 010 | Watcher, operator, auto-mode |
| 011 | Dashboard, events, observability (Langfuse) |
| 012 | Guard and security (redaction, dangerous patterns, checkpoint) |
| 013 | MCP server and approvals |
| 014 | Modules and gateway |
| 015 | Memory, recall, distill, behavioral profile |
| 016 | Installation, hooks, release/tag/publish separation |

## Status of this breakdown

This is an assumption drawn from the source tree and the section headings of `docs/ARCHITECTURE.md`. The code of each area has not yet been read.

Suggested starting point: 004 and 006, because both already have tests, so their test bindings can be real.
