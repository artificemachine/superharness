# Job-Ready Final Scorecard — superharness
**Date:** 2026-07-20 (loop conclusion; initial audit 2026-07-19)
**Audited at:** main `2b4c6eea` · v1.80.2 on PyPI
**Method:** full /job-ready (stages 1-8) + three fix waves + independent per-stage re-verification on the merged tree.

| # | Stage | Verdict | Evidence |
|---|-------|---------|----------|
| 1 | First impression | PASS | Badges, description, topics, community files (COC, issue/PR templates), canonical Apache-2.0 text, dependabot. Personal-data leak fully scrubbed (incl. audit-report re-leak). |
| 2 | Git history & releases | PASS | 727+ conventional commits; tags=pyproject=releases in sync; release notes backfilled v1.76.0-v1.80.2; branches 228→71 (all provably-safe classes deleted). |
| 3 | README + docs | PASS | 15/15 relative links resolve; version claims de-hardcoded (PyPI badge is the source); docs index exact (112 active/39 archived, 0 orphans). |
| 4 | Fresh clone + deps | PASS | Clean clone → venv → install → `--help` → 17-step demo, all exit 0. pip-audit: 0 shippable-package CVEs. `requests` declared. Suite: 3472 passed (reproduced twice) + 3-platform CI green. |
| 5 | Gauntlet | PASS | Deadline bug fixed (+dual watchdog), coverage gate live (--cov-fail-under=53), concurrent-writer chaos tests, dispatch injection-safe (argv-quoted, test-pinned), status hard guard. |
| 6 | Architecture | PASS (with debt register) | CRITICAL DB-path drift fixed; pragma consistency; JSON hardening; index idempotency. Open MEDIUMs below. |
| 7 | CI governance | PASS | SHA-pinned actions, OIDC publish, hard security gates, least-privilege permissions on all 4 gate workflows. |
| 8 | Claims vs reality | PASS | Source-of-truth claim, test counts, CVE claims all verified true; version claims now unfalsifiable by design. |

## Verdict: HIRE-READY

All hard gates cleared and independently verified in clean environments. Shipped
during the loop: v1.79.1 (gates), v1.80.0 (steal-list hardening, 46 tests),
v1.80.1 (presentation), v1.80.2 (arch hardening, 30 tests), plus 5 docs/chore
merges. Suite grew 3400 → 3472 passing.

## Open debt register (documented, non-blocking, owner-decision or own-plan scale)

1. **Stage 6 MEDIUMs**: no FK constraints on `failures`/`decisions`/`ledger.task_id`;
   `tasks.parent_id` lacks ON DELETE; migration-drift healing hardcoded to v25.
   Fix = table-rebuild migrations; deserves its own /plan-iter.
2. **Watcher god-module**: `inbox_watch.py` 4.6k lines; 1 of 3 mirror sites not yet
   on the live_state chokepoint. Split plan seeded by the harness registry
   (v1.80.0); own refactor plan.
3. **49 stale remote branches with unique commits** — operator judgment required
   (deletion loses real work). List: session scratchpad `stale-branches.txt`
   (regenerate: `git branch -r` + `git cherry origin/main`).
4. **telegram `/reset` → `"pending"`** latent bug now fails loudly (ValueError);
   intended target status = owner decision.
5. **4 env-sensitive tests** (`test_init_project` ×2, `test_update_command` ×2)
   assert machine-specific install branches — pass in CI, fail on dev machines
   with pipx-installed shux. Candidate: env-branch the assertions.
6. **GitHub license detection** still `NOASSERTION` despite canonical 201-line
   Apache-2.0 text (kubernetes-identical filled-notice form) — licensee cache or
   quirk; content-side complete, re-check in a day.

## Loop audit trail
- Initial audit: docs/audits/2026-07-19-job-ready.md + job-ready-progress.md
- Fix-wave PRs: #43 (v1.79.1), #48 (v1.80.0), #49 (v1.80.1), #50 (v1.80.2), #51, #52
- Steal-list source study: docs/STEAL-LIST-omnigent-2026-07-19.md; plan + build
  outcome: docs/PLAN-steal-omnigent.md
