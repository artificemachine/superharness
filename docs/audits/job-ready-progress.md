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

---

## Run 2026-07-20 (re-audit at v1.81.0, post-PR#55)

- **Stage 1 — First impression: PASS (3 LOW findings)**
  - metadata/topics/default-branch/community-files/binaries: all clean
  - gitleaks: 2 hits, both `tests/unit/test_module_obsidian.py:211` — confirmed FAKE fixture (`sk-1234567890abcdef`). Not a secret.
  - LOW: no screenshot/demo above the fold (carried from 2026-07-19, still open)
  - LOW: `airm2max` in 3 tracked files (`.shipguard.yml:43` intentional blocklist; `docs/bugs/*.md:3` "Reporter:" x2)
  - LOW: GitHub license API still `NOASSERTION` despite canonical 201-line Apache-2.0 (carried, >24h — not a cache flush)
- **Stage 2 — Git history & releases: FAIL (1 blocker)**
  - commits excellent: 1154/1196 conventional (96.5%); recent 30 all clean; the lone "WIP on" is stash-only, not in history
  - BLOCKER: `pyproject` = 1.81.0 but **no v1.81.0 tag, no release, PyPI still 1.80.2** — main claims a version that was never published
  - 78 remote branches (target <20); 4 merged-undeleted; 1 non-semver tag `adapter-payload-verified`
- **Stage 4 — Fresh clone + deps: FAIL (1 HIGH blocker)**
  - fresh clone + venv install + CLI smoke: PASS (`superharness, version 1.81.0`)
  - **HIGH / REGRESSION (PR #55, mine): v33 FK guard is cosmetic and crashes the upgrade path.**
    `_run_single_migration` runs `PRAGMA foreign_key_check` in the `finally` block — i.e. AFTER
    `with transaction(conn)` already committed the migration and set `user_version=33`. Raising
    SchemaError there cannot roll anything back.
    Reproduced deterministically on a scratch v32 DB with one planted orphan row:
    `init_db` RAISED SchemaError, yet ended at `user_version=33`, `violations=1`, orphan row intact.
    Confirmed live: this user's own production DB is at v33 **with 3 real FK violations**
    (ledger ids 32/33/34, `task_id='smoke.b1'`, dated 2026-05-15 — pre-existing dangling rows).
    The raise was swallowed by an upstream `except Exception`, which is why it went unnoticed.
    Impact: any user upgrading 1.80.2 -> 1.81.0 whose DB has a dangling `task_id` gets a
    SchemaError on first command. Migration v33 never NULLs pre-existing orphans, so it
    permanently installs a constraint its own data violates.
    Fix: (a) v33 should NULL orphaned task_id during the table rebuild (matches ON DELETE SET NULL
    semantics); (b) move the FK check inside the transaction, before RELEASE SAVEPOINT.
- Stages 3, 5, 6, 7, 8: NOT RUN — halted on the Stage 4 HIGH blocker.

- **Stage 7 — CI governance: NEEDS HARDENING (2 HIGH)**
  - HIGH: `security.yml:29` `shipguard scan . | tee shipguard.txt` — GitHub's default `bash -e {0}`
    has no `pipefail`, so the step exits with tee's status (0). A scan finding CRITICALs passes the
    build. Verified empirically: `bash -e -c 'false | tee /dev/null'` -> exit 0. No `pipefail`,
    `shell:` or `defaults:` in any of the 6 workflows. (`pip-audit` at :47 writes to a file with no
    pipe, so that one does block.)
  - HIGH: `main` has NO branch protection — verified `protected:false`,
    `required_status_checks.enforcement_level:"off"`, `contexts:[]`, `rulesets:[]`. The aggregator
    gates (`qa-gate` tests.yml:166-200, `windows-native-gate` ci-matrix.yml:103-129) are correctly
    written with `if: always()` + `needs.*.result == success`, but nothing requires them, so all 27
    jobs are advisory. Directly explains how PR #55 merged with Windows unit tests failing.
  - MED: `pypi`/`testpypi` environments have empty `protection_rules` + null
    `deployment_branch_policy`, while `publish.yml:6-11,23` accepts an arbitrary `ref` via
    workflow_dispatch -> any write-access user can publish arbitrary code from any branch.
    (OIDC trusted publishing itself is correct — no long-lived token.)
  - MED: coverage gate blocking but set to 53% (`tests.yml:102,114`)
  - LOW: unpinned test deps (tests.yml:74,98,135,158; ci-matrix.yml:38,64) vs correctly pinned
    scanners (`shipguard==0.3.2`, `pip-audit==2.7.3`)
  - LOW: ShipGuard log truncated to 260 lines (`security.yml:30`); full report still uploaded as artifact
  - CLEAN: zero `continue-on-error`, zero `|| true`, no `pull_request_target`, all actions SHA-pinned,
    all 6 workflows declare `permissions:`, secrets only via `GH_TOKEN` env (never echoed)
