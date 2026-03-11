# Public Readiness Re-Audit Report

- Task: `public-readiness-reaudit-20260311`
- Contract: `v08-reliability`
- Date: `2026-03-11`
- Target repo: `/Users/airm2max/DevOpsSec/superharness`
- Branch audited: `chore/ship-hardening-pass`
- Worktree state: `dirty` (`.superharness/inbox.yaml` modified before this audit)
- Release verdict: `No-Go`

## Summary

Re-audited the current March 11, 2026 working state of `/Users/airm2max/DevOpsSec/superharness` for public GitHub readiness.

The previously reported high ShipGuard blocker is fixed, and the documented quickstart still works on a clean temp HOME/project. `superharness doctor --project . --check` and `superharness hygiene --project .` both passed, and the CI governance posture is fail-closed.

The repo still does not meet the requested "all blockers fixed, clean go verdict" bar:

1. `CONTRIBUTING.md` is still missing from the repo root.
2. `LICENSE` is still missing from the repo root.
3. `pytest tests/ -q` still fails in the current worktree.
   - `tests/unit/test_delegate.py::test_delegate_claude_non_interactive_requires_specific_skip_permissions_confirmation`
   - `tests/unit/test_uninstall.py::test_uninstall_all_removes_lock_dirs`

## Gate Results

- Quickstart/onboarding: pass
  - Clean temp-HOME replay succeeded for install-wrapper, `init`, `doctor`, `task create`, `enqueue`, and `dispatch --print-only`.
- Doctor: pass with warning
  - `./superharness doctor --project . --check` returned 0 failures and 1 warning (`watcher` not loaded).
- Protocol hygiene: pass
  - `./superharness hygiene --project .` passed.
- Security pipeline: pass
  - `shipguard scan . --format terminal` reported 0 findings.
- CI governance gate: pass
  - Required workflows present: `tests.yml`, `security.yml`, `shell-guard.yml`, `contract-hygiene.yml`.
  - No broad `continue-on-error: true` in CI workflows.
  - No unconditional `|| true` neutralizing blocking scan steps in CI workflows.
  - No mutable `:latest` scanner/runtime images in workflows.
  - Workflow actions are SHA pinned.
- Infra gate: not applicable
  - No repo deployment target artifacts (`docker-compose.yml`, `compose.yml`, `.env*`) were found, and this task scope was source-repo public readiness rather than live-service exposure.
- Release docs gate: fail
  - No repo-root `CONTRIBUTING.md`.
  - No repo-root `LICENSE`.
- Test gate: fail
  - `pytest tests/unit/test_delegate.py -q` failed 1 test.
  - `pytest tests/ -q` failed 2 tests, 194 passed, 6 skipped.

## Blocking Findings

1. Missing public repo essentials: `CONTRIBUTING.md` and `LICENSE`.
2. Delegate confirmation gate is still regressed for Claude non-interactive launch confirmation.
   The test expected `scripts/delegate.sh` to reject `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES` without a separate `SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES`, but the script returned success instead.
3. `scripts/uninstall.sh --all` still exits non-zero in this environment when removal of `~/Library/LaunchAgents/com.superharness.inbox.*.plist` hits `Operation not permitted`.
   Public release claims should not say the full suite is green while this test still fails.

## Evidence Reviewed

- `pytest tests/unit/test_delegate.py -q`
- `pytest tests/ -q`
- `./superharness doctor --project . --check`
- `./superharness hygiene --project .`
- `shipguard scan . --format terminal`
- `README.md` and `docs/QUICKSTART.md`
- `.github/workflows/*.yml`
- Repo-root presence check for `CONTRIBUTING.md` and `LICENSE`

## Verdict

Wait for maturity.

This re-audit is closer than the first review because the ShipGuard blocker is gone and the documented onboarding path still works. It is still not ready for a public GitHub release. The verdict remains `No-Go`.

## Recommended Next Steps

1. Add a real repo-root `LICENSE`.
2. Add a minimal repo-root `CONTRIBUTING.md`.
3. Fix the delegate non-interactive confirmation gate so `tests/unit/test_delegate.py::test_delegate_claude_non_interactive_requires_specific_skip_permissions_confirmation` passes.
4. Fix or harden `scripts/uninstall.sh --all` so `tests/unit/test_uninstall.py::test_uninstall_all_removes_lock_dirs` passes cleanly.
5. Re-run:
   - `pytest tests/ -q`
   - `shipguard scan . --format terminal`
   - `./superharness doctor --project . --check`
   - `./superharness hygiene --project .`
