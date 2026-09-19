# AUDIT — docs/ merge and archive triage (2026-09-18)

Scope: the 64 git-tracked markdown files under `docs/`, excluding `docs/archive/`
and `docs/README.md`. Two questions were asked of the set: which documents
overlap enough to become one, and which are superseded enough to leave the
active tree.

## Method

`git ls-files` for the tracked surface, `git check-ignore -v` to separate
tracked documents from the gitignored working notes that also live under `docs/`
(`docs/PLAN-*.md`, `docs/bulletproof-report-*.md`, `docs/audits/*-portfolio-ready.md`,
`docs/audits/*-golive.md`). Overlap was judged by shared subject, same-day
authoring and mutual cross-reference rather than by filename alone. Archive
candidacy was judged by the document's own status line and by whether a newer
dated run of the same series exists. Every inbound reference was located before
anything was moved, because a merge or a move that breaks a link has not finished.

## Merges performed

| Result | Sources | Basis |
|---|---|---|
| `CONCEPT-openprose-reactor.md` | `ADAPTATION-openprose-reactor.md` (2,628 B), `CONCEPT-openprose-reactor-pilot.md` (2,384 B), `ARCH-openprose-superharness-sdd.md` (1,477 B) | Same week, same subject, and `CONCEPT-openprose-reactor-pilot.md` already cross-referenced the other two. Contents preserved verbatim as Parts 1–3 with internal headings demoted one level; `REFERENCE-openprose-crossprose.md` deliberately stays separate because it is the ownership boundary with the companion `crossprose` repository |
| `CONCEPT-develop-until-approved.md` | folded in `FLOW-pi-develop-issues-until-approved.md` (3,147 B) | Same feature, same day (2026-08-01); the CONCEPT already named the FLOW as its source design doc. Folded in as Appendix A, and the CONCEPT's source pointer now points at the appendix |

Both merges used `git mv` on the largest source so its history survives, and the
folded sources were removed only after a heading-parity check showed that the
only headings absent from the merged file were the three (respectively one)
replaced H1 titles.

## Archives performed

| Document | Basis |
|---|---|
| `morpheme-branch-policy.md` | The document itself opens with `Status (2026-04-16): retiring the superharness-side paired branch … preserved for historical`, and the index already labelled it "(retired)" |
| `audits/2026-07-21-arch-audit.md`, `audits/2026-08-05-arch-audit.md` | Same-titled dated series, superseded by the current `audits/2026-09-10-arch-audit.md` |
| `audits/2026-08-05-bulletproof.md` | Superseded dated claims-vs-reality run |

`docs/archive/` went from 28 to 32 tracked files. Inbound references were updated
in `docs/README.md`, `CLAUDE.md`, `docs/audits/2026-07-21-portfolio-ready.md` and
`docs/audits/2026-08-05-golive.md` — the last two are gitignored local run
artifacts, updated so their provenance lines keep resolving on this machine.

## Deliberately not done

- **`brain-multi-agent-tiers-fleet.md` was not merged into `brain-scan-2026-07-12.md`.**
  The pairing was proposed on the strength of a shared date and adjacent index
  rows, but the file carries 10 inbound references, including
  `tests/unit/test_onboard_fleet_ipv4.py:5` and three in
  `docs/plans/PLAN-superharness-L5.md`. Ten link rewrites are not worth a merge
  whose only justification is a shared date. Its content is conceptual reference
  material (why four agent CLIs, what the tiers mean, the GPU fleet) which would
  also be partly buried inside a dated scan.
- **No document was re-classified on content that was not read.** Three
  candidates were judged by title, date and size only and are recorded here as
  unverified: `CONCEPT-enforcement-parity.md` possibly overlapping
  `TEST_STRATEGY.md`; `inter-agent-talk-protocol.md` possibly overlapping
  `CONCEPT-notifications-and-state-isolation.md` and `DISCUSS.md`; and whether
  `RUNBOOK-state-authority-stage1-transition.md`'s stage 1 actually completed.
- **`yaml-inventory.md` was explicitly left alone.** It self-describes as
  tracking "Keep — Operator-Authored Config (always YAML)", so it needs a
  freshness check against the current YAML surface, not a move.

## Remaining gap

Indexing, not pruning, is the larger defect. 15 of the 64 tracked documents were
named in no index section before this pass; the merged and archived work above
brought that to 6:

- `ANALYSIS-lean-feature-hierarchy.md`
- `ARCH-exo-vs-superharness.md`
- `CONCEPT-enforcement-parity.md`
- `inter-agent-talk-protocol.md`
- `RUNBOOK-state-authority-stage1-transition.md`

## Verification

- `tests/test_docs_index_links.py` passes (every relative `.md` link in
  `docs/README.md` resolves to a git-tracked file).
- A repository-wide sweep of every relative `.md` link in all 90 tracked
  documents under `docs/` found **0** unresolved targets.
- Heading-parity checks for both merges pass; no source heading was lost.
- No dangling reference to a moved document remains in the tracked surface.

## Note on the OpenProse documents

`HANDOFF.md:335` recorded the four OpenProse documents as "Untracked files …
Leave alone until the operator says what they are", and `HANDOFF.md:489` says
"Do NOT act on them without a fresh operator decision". This audit reorganises
their text only, on an explicit operator instruction. Every source document
states that no integration is approved or implemented, and nothing here changes
that: no reactor mechanism, adapter or `.prose.md` pipeline was added.
