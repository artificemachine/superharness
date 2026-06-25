# Morpheme Integration — Branch Policy

> **Status (2026-04-16): retiring the superharness-side paired branch.** The
> adapter-payload contract stabilised at schema v1.1 and ships via PyPI on
> every release. All superharness work now lands on `main` directly via
> regular feature branches. The document below is preserved for historical
> reference; see **"Retirement note"** at the bottom for the current policy.

This document originally mirrored what was done in the `artificemachine/morpheme` repo to keep the
superharness side consistent during the Phase 2 integration co-design (v1.16.0 through v1.21.0).

---

## Context

Both repos share a paired integration branch:

| Repo | Branch |
|------|--------|
| `artificemachine/morpheme` | `feat/superharness-integration-morpheme` |
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
cd <path/to/superharness>
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

---

## Retirement note (2026-04-16)

The paired-branch convention is retired on the superharness side starting
with v1.24.2. Rationale:

- **Schema is stable.** Adapter-payload contract reached v1.1 (resolved_model
  field). Future changes will be minor additions, not breaking renegotiations.
- **Producer–consumer, not co-design.** Superharness is now the sole
  producer of the JSON payload. Morpheme is one of potentially many
  consumers. There is no two-way iteration to coordinate via a shared
  branch name.
- **Every release ships on PyPI.** Morpheme should pin a superharness
  version in its own manifest and upgrade like any other dependency.
  Cross-repo branch pairing added ceremony without reducing risk.

### What changes

- Superharness-side branch `feat/superharness-integration-morpheme` is
  **synced one last time** with main (chore merge including v1.24.2) so
  Morpheme has a stable reference point, then **left dormant**. It will be
  deleted after Morpheme's UI consumption PR lands.
- All future superharness adapter-payload work goes through `main` via
  normal feature branches → PR → merge.
- Morpheme keeps its own `feat/superharness-integration-morpheme` branch
  (or renames it — their call) and treats superharness as a regular
  upstream: pin a version, upgrade as needed.
- `CLAUDE.md` and `AGENTS.md` "Cross-Repo Branch Link" sections are kept
  for historical context but marked as "retired" rather than deleted.

### What does NOT change

- The `celstnblacc/superharness` repo URL itself (only the Morpheme repo
  moved, to `artificemachine/morpheme`).
- The `adapter-payload-verified` tag stays on both repos as a permanent
  marker of the v1.16.0 integration checkpoint.
- Existing handoffs, failures, decisions, and contract history under
  `.superharness/` — untouched.

### How Morpheme consumes superharness going forward

1. Pin `superharness>=1.24.2` in whatever manifest applies (or just invoke
   the packaged `shux` binary).
2. Read schema version from `adapter-payload --json` output and accept any
   1.x (1.0 through 1.x current).
3. Upgrade pins when a useful new field lands.
