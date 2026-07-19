# /job-ready progress — superharness (--quick)

Run date: 2026-07-19

## Stage 1 — Recruiter First-Impression Gate: FAIL (fixable fast)

PASS items:
- Repo metadata: description set, 12 topics, default branch `main`, public. Good.
- LICENSE: Apache-2.0 text present.
- No secrets: gitleaks over 1124 commits — only 2 hits, both fake fixtures in `tests/unit/test_module_obsidian.py:211` (redaction test: `sk-1234...`, `ghp_abc...`). Not real.
- No binaries/droppings tracked.
- Community: SECURITY.md, CONTRIBUTING.md, CHANGELOG.md present.

FAIL items:
1. **Zero badges in README** — no CI, no PyPI, no license badge. Repo has CI + PyPI releases; not showing them wastes the strongest proof signals.
2. **Stale "What's New in v1.44.21" section in README** (line ~20) while repo is at v1.79.0 — reads as unmaintained docs at first scroll.
3. Personal-data residue in tracked files (public repo): `$HOME` paths in HANDOFF.md, docs/CONCEPT-notifications-and-state-isolation.md, docs/bugs/* (3 files), docs/PLAN-portable-*.md (2), tests/unit/test_logging_utils.py (~10 occurrences total); real homelab LAN IPs in HANDOFF.md:50,56,405 (<LAN-gpu-endpoint>, <LAN-vidistiller-host>).
4. GitHub shows license as "other" — licensee fails to detect the 183-line Apache-2.0 variant (appendix stripped). Replace with canonical text.
5. Missing: CODE_OF_CONDUCT.md, `.github/ISSUE_TEMPLATE/`, PR template — community-standards page shows gaps.
6. README has no License section at all.

## Stage 2 — Git History & Release Hygiene: FAIL (one big item)

PASS items:
- Commit quality excellent: 727 commits, conventional format throughout recent history, PR-numbered; only 1 wip-class word in the entire log. No reword/squash needed.
- Merge topology clean, no back-merge noise.
- Tags: 83 semver tags; v1.79.0 tag = pyproject version = latest GitHub release. Perfect sync.
- Repo shape: real incremental history, no code-dump.

FAIL items:
1. **228 remote branches** (235 local). Branch page is unreadable; screams "never cleans up". 32 merged into main → safe delete; ~196 stale unmerged experiment branches → review-then-delete.
2. **Release notes are empty shells**: v1.79.0 body = "See CHANGELOG.md for details." Every release the same. Releases page shows 83 releases with no content.
3. Local HEAD on `docs/handoff-2026-07-15` (1 ahead / 2 behind main) — unmerged branch pending.

### Cleanup Plan

Safe (no history rewrite):
- Delete 32 remote branches merged into origin/main (`git push origin --delete ...` batch).
- Triage remaining ~196 unmerged remote branches: delete all with no unique commits worth keeping (bulk candidates: `chore/bump-*`, `chore/release-*` — release mechanics, worthless post-merge).
- Mirror cleanup locally (~235 local branches).
- Backfill release notes for at least the last 5-10 releases from CHANGELOG sections (`gh release edit vX -n "..."`).
- Merge or close the open `docs/handoff-2026-07-15` branch.

Rewrite (needs force-push) — NOT recommended:
- None. History is good; personal-path scrub via filter-repo not worth the disruption (paths are in docs, not secrets). Fix HEAD copies instead.

## Stage 3 — README + docs: FAIL

README (NEEDS WORK, 9 FAIL / 6 WARN):
- 0 badges, 0 visuals (dashboard tool with no screenshot)
- Version claims 35 releases stale: "v1.44.21" at README:16 and README:356; "151 tests" stale
- 4 broken copy-paste paths: README:83, 90, 320, 329 (scripts moved to src/superharness/scripts/)
- 2 broken doc links: README:342, 346 (files moved to docs/archive/)
- README:284-292 "Project Runtime State" describes YAML as state — contradicts README:21 and project doctrine (state.db is SSOT)
- Quickstart itself PASS: all spot-checked commands exist in cli.py

Docs organization (FAIL):
- docs/README.md index 2 months stale: claims 61 active docs, actual 125; 63 orphans (50%)
- 14-file bulletproof-report near-duplicate series in active tree
- Dated HANDOFF-2026-06-*.md and RELEASE-TODO-v1.62.15.md posing as active docs
- Naming split-brain: PLAN-/plan-/plans/ three competing conventions

## Stage 9 — Scorecard: written to docs/audits/2026-07-19-job-ready.md
Verdict: NOT READY (personal-data hard gate); rest = polish grade.
