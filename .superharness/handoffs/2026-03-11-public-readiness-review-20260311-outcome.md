# Public Readiness Review Report

- Task: `public-readiness-review-20260311`
- Contract: `v08-reliability`
- Date: `2026-03-11`
- Target repo: `/Users/airm2max/DevOpsSec/superharness`
- Branch audited: `chore/ship-hardening-pass`
- Worktree state: `dirty`
- Release verdict: `No-Go`

## Summary

Audited the current March 11, 2026 working state of `/Users/airm2max/DevOpsSec/superharness` for public GitHub readiness.

The good news: the README explains the product clearly, the literal quickstart reproduced on a clean temp project, the main CLI help is usable, and `superharness hygiene --project .` passed.

The blockers are concrete and release-stopping:

1. `CONTRIBUTING.md` is missing.
2. `LICENSE` is missing.
3. `pytest tests/ -q` failed with 2 security-gate regressions in `tests/unit/test_delegate.py`.
4. `shipguard scan . --format terminal` reported 1 `HIGH` finding (`PY-004`) in `scripts/monitor-ui.py`.

## Dimension Scores

- First impression: green
- Onboarding realism: green
- CLI ergonomics: yellow
- Value proposition: green
- Failure surface: red
- Trust and readiness: red

## Top 3 Strengths

1. README communicates the tool, target users, and quick links fast enough for a first-time adopter.
2. Fresh-machine onboarding reproduced successfully with a temp `HOME`: wrapper install, `init`, `doctor`, `task create`, `enqueue`, and `dispatch --print-only`.
3. CLI surface is reasonably discoverable: `superharness --help`, `doctor --help`, and `uninstall --help` are clear, and uninstall/dry-run paths exist.

## Top 3 Blockers

1. Missing public repo essentials: `CONTRIBUTING.md` and `LICENSE` do not exist in the repo root.
2. The automated trust story is broken right now: `pytest tests/ -q` failed 2 tests.
   - `test_delegate_claude_non_interactive_requires_specific_skip_permissions_confirmation`
   - `test_delegate_codex_bypass_requires_specific_confirmation`
   These failures show the unattended launch confirmation gates are not behaving as expected in the current worktree.
3. ShipGuard is not clean: 1 `HIGH` finding (`PY-004`) was reported in `scripts/monitor-ui.py`.
   The current implementation constrains report reads to `.superharness/handoffs/`, but it should still be rewritten using `Path.is_relative_to(...)` or equivalent to clear the scanner and make the boundary check explicit.

## Additional Evidence

- `./superharness doctor --project . --check` returned 0 failures and 1 warning.
  The only warning was that the watcher service was not loaded, which is expected unless background watching has been installed.
- `superharness hygiene --project .` passed.
- Tracked source/docs scan found no hardcoded `/Users/...` paths outside protocol state and tests.
- No obvious committed secrets were found by the targeted scan used for this review.
- `CHANGELOG.md` is present and had no working-tree diff during this audit.

## Verdict

Wait for maturity.

For a skeptical external adopter, this is close enough to try in a controlled environment, but not ready for a public GitHub release yet. For a public release gate, the verdict is `No-Go`.

## Recommended Next Steps

1. Add a real `LICENSE` file and a minimal `CONTRIBUTING.md`.
2. Fix the delegate confirmation-gate regression in `scripts/delegate.sh`, then rerun `pytest tests/ -q`.
3. Fix or explicitly justify the ShipGuard `PY-004` finding in `scripts/monitor-ui.py`, then rerun `shipguard scan . --format terminal`.
4. Re-run this audit from a clean commit or reviewed release branch instead of a dirty worktree.
