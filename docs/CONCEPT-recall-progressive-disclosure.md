# CONCEPT: 3-layer progressive-disclosure pattern for `shux recall`

Status: proposal, not committed
Captured: 2026-05-11
Origin: audit of thedotmack/claude-mem MCP search surface

## Context

Different problem space from claude-mem (passive memory vs. our task orchestration), but their MCP search pattern is worth stealing.

The pattern (theirs):

1. `search(query, filters)` returns a compact index: IDs + ~50–100 tokens per hit.
2. `timeline(id)` returns chronological neighbors of an interesting hit.
3. `get_observations(ids=[...])` returns full bodies only for filtered IDs (~500–1,000 tokens each).

Claim: ~10× token savings by filtering on the index before fetching bodies.

## What I want in superharness

- `shux recall <query>` today returns full handoff bodies via FTS5. On a contract with 50+ closed tasks this blows context fast.
- Split into:
  - `shux recall --index <query>` returns IDs + one-line headlines + status + date.
  - `shux recall --fetch <id> [<id>...]` returns full bodies for the chosen IDs.
- Add `shux recall --timeline <id>` to show the N tasks immediately before/after a given task on the same project.
- Keep current `shux recall <query>` as a shortcut for index + auto-fetch top-1.

## Why it matters

- The cost gate in CLAUDE.md (>100k tokens → `/compact`) means recall over a long contract is currently a context grenade.
- Same FTS5 backend, no new dependencies, no Chroma. Purely a CLI surface + token-budget change.

## Non-goals

- Not adopting claude-mem itself (wrong tool for our handoff problem).
- Not adding vector search yet — FTS5 + this pattern is probably enough.

## Next step when promoted

Create a shux task with a TDD plan: red tests assert index output stays under N tokens for a seeded 50-task contract; green implements the split; refactor consolidates the FTS5 query path. Public CLI change → needs owner approval before `plan_approved`.
