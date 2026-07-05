# Repo Migration — Fork Situation (2026-06-28)

## Context

Superharness migrated from `celstnblacc/superharness` to `artificemachine/superharness`.
On 2026-06-28, one external contributor (`yjjoeathome-byte`) forked the old repo.

## Current State

| Repo | Archived | Last Push | Forks | Stars |
|------|----------|-----------|-------|-------|
| `celstnblacc/superharness` | No | 2026-06-25 | 2 | 3 |
| `artificemachine/superharness` | No | 2026-06-26 | 0 | 0 |

The old repo is still live, public, and not archived. It appears authoritative to anyone who finds it via search or star history.

## What Happens to the Fork

- `yjjoeathome-byte/superharness` is permanently linked to `celstnblacc/superharness` as parent
- GitHub has no mechanism to re-parent forks to a new canonical repo
- If `celstnblacc/superharness` is archived: their fork stays intact but PRs to the parent are blocked
- If `celstnblacc/superharness` is deleted: GitHub promotes the most active fork to independent root — their fork becomes orphaned from the network entirely
- In either case, they never automatically discover `artificemachine/superharness`

## Options

1. **Do nothing** — they forked an old snapshot; their problem to find the new repo
2. **Open a GitHub issue on their fork** — leave a notice pointing to `artificemachine/superharness`
3. **Archive `celstnblacc/superharness` + add README redirect notice** — lowest effort, covers all future visitors including the forker

## Recommended Action

Option 3:
- Add a notice at the top of `celstnblacc/superharness` README pointing to `artificemachine/superharness`
- Archive the old repo so it no longer appears active

This does not fix the fork's parent link but makes the canonical repo discoverable to anyone who lands on the old repo.
