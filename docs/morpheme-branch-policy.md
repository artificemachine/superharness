# Morpheme Integration — Branch Policy

**⛔ DO NOT RELEASE** — this branch is not ready for PyPI publish. No tag/release/publish without explicit owner instruction.

This document mirrors what was done in the `celstnblacc/morpheme` repo so the
superharness side stays consistent.

---

## Context

Both repos share a paired integration branch:

| Repo | Branch |
|------|--------|
| `celstnblacc/morpheme` | `feat/superharness-integration-morpheme` |
| `superharness` (this repo) | `feat/superharness-integration-morpheme` |

The branch implements Phase 2 of the Morpheme integration:
`shux adapter-payload --json` (superharness side) + adapter boundary layer
(Morpheme side). Both branches are verified working as of 2026-04-12.

---

## What Was Done in Morpheme

### 1. Branch renamed

`explore/superharness-gallery` → `feat/superharness-integration-morpheme`

Reason: match the superharness branch name so the pair is unambiguous.

### 2. Checkpoint tag created

```bash
git tag adapter-payload-verified
```

Applied on the commit where `shux adapter-payload --json` was confirmed working
end-to-end (`[adapter] shux adapter-payload v1.0 — 73 tasks` firing on every
connect and file-change event, `rawParser.js` never called).

The tag is a permanent reference to the verified state regardless of what
happens to the branch later.

### 3. Merge policy note added to CLAUDE.md and AGENTS.md

```
## Branch Merge Policy

Branch fate undecided — may merge into main or become a standalone module.
Do not merge PRs without explicit instruction.
```

Reason: it is not yet decided whether this branch merges into `main` or becomes
a standalone package/module. The note prevents accidental merges by any agent
or automation.

---

## Action Required in This Repo (superharness)

### 1. Create the same checkpoint tag

```bash
cd ~/DevOpsSec/superharness
git tag adapter-payload-verified
```

Apply it on the commit that shipped `commands/adapter_payload.py` (v1.16.0),
after the task `feat.morpheme-phase1-smoke` was verified pass.

### 2. Add the merge policy note to CLAUDE.md

Append this section before the `## CHANGELOG Policy` section:

```markdown
## Branch Merge Policy

Branch fate undecided — may merge into main or become a standalone module.
Do not merge PRs without explicit instruction.
```

### 3. Add the same note to AGENTS.md

Same section, same wording, same placement (before `## CHANGELOG Policy`).

---

## Verification Record

The Morpheme-side verification was recorded via:

```bash
shux verify --id feat.morpheme-phase1-smoke \
  --method "morpheme start — [adapter] shux adapter-payload v1.0 — 73 tasks \
fires on every connect and file-change; rawParser never called" \
  --result pass
```

Handoff: `.superharness/handoffs/feat.morpheme-adapter-payload-report-2026-04-12-claude-code.yaml`

---

## State Summary (2026-04-12)

| Item | Morpheme | superharness |
|------|----------|--------------|
| Branch | `feat/superharness-integration-morpheme` | `feat/superharness-integration-morpheme` |
| Tag | `adapter-payload-verified` ✓ | `adapter-payload-verified` ✓ |
| CLAUDE.md merge policy | Added ✓ | Added ✓ |
| AGENTS.md merge policy | Added ✓ | Added ✓ |
| PR | #4 open, do not merge | n/a |
| Verification | `feat.morpheme-phase1-smoke` — PASS ✓ | — |
