# Tests Still Need

This document lists missing test coverage for `superharness` and prioritizes what to implement next.

## Unit Tests
- `init-project.sh`
- Argument parsing (`--help`, `--dry-run`, invalid flags).
- Idempotency and existing `.superharness` handling.
- Generated file content assertions for `contract.yaml`, `CLAUDE.md`, `AGENTS.md`.
- `adapters/claude-code/install.sh`
- Symlink lifecycle: not installed, already installed, wrong symlink target, target path exists as directory.
- `scripts/install-git-hooks.sh`
- `--dry-run`, `--force`, existing `core.hooksPath` behavior.
- Hook scripts
- `branch-guard.sh`: block/warn/allow matrix using JSON fixtures.
- `scope-guard.sh`: sensitive file blocking, system path warnings, allow behavior.
- `ledger-append.sh`: append behavior, skip rules, no-ledger behavior.
- `session-start.sh`: output JSON schema + required fields.
- `scripts/check-shell-entrypoints.sh`
- Allowlist drift detection.
- Missing file, non-executable mode, missing shebang, syntax error failure paths.

## Integration Tests
- Bootstrap integration
- Run `init-project.sh` in temp repo and assert full `.superharness/` tree + generated docs.
- Git hook integration
- Run `scripts/install-git-hooks.sh`; verify `core.hooksPath` and execute `.githooks/pre-commit` in a temp git repo.
- Hook protocol integration
- Feed representative hook payload JSON into each hook script and validate responses.

## End-to-End (E2E) Tests
- Fresh clone -> install -> initialize -> complete one task/handoff cycle.
- Validate protocol artifacts (`contract`, `handoff`, `ledger`) and guard behavior throughout.
- Policy enforcement E2E
- Attempt blocked operations (`git push main`, `.env` write) and assert block/warn actions.

## Smoke Tests
- Keep current command smoke tests in CI.
- Add runtime smoke that executes each hook with a minimal valid JSON input and asserts no crash + valid output.

## Regression Tests
- Golden-file tests for generated `CLAUDE.md` and `AGENTS.md`.
- Cross-platform behavior checks (macOS/Linux) for shell/Python replacement paths and quoting-sensitive flows.

## Security Tests
- Negative tests for command injection attempts in template substitution.
- Secret-handling policy tests for `.env`, `*.pem`, `*.key`, and credential-like paths.
- CI policy tests that fail on fail-open security posture regressions.

## Reliability / Ops Tests
- Automated temporary Docker staging probe scenario (redis/postgres auth, health, resource limits).
- Healthcheck + restart policy assertions for future compose assets.

## Priority Order
1. Unit tests for shell scripts and guard logic.
2. Integration tests for bootstrap + hook install.
3. E2E policy enforcement tests.
4. Regression/golden-file tests.
5. Dockerized reliability/ops test automation.
