## What

<!-- What does this PR change? -->

## Why

<!-- Why is this change needed? What problem does it solve? -->

## Version bump

<!-- feat -> minor, fix/security/chore -> patch, BREAKING CHANGE -> major. Mark one. -->

- [ ] No version bump needed (docs/test/chore only)
- [ ] Patch (`fix`, `security`, `chore`)
- [ ] Minor (`feat`)
- [ ] Major (`BREAKING CHANGE`)

## Tests

- [ ] Offline suite: `pytest tests/ -q` passes (no provider or agent CLI)
- [ ] Live-provider smoke test run when relevant: `SUPERHARNESS_ALLOW_LIVE_TESTS=1 RUN_PROVIDER_SMOKE=1 pytest tests/integration/test_summarizer_smoke.py -q`
- [ ] `shipguard scan .` passes
- [ ] New/changed behavior has test coverage (TDD: failing test added first)
- [ ] `CHANGELOG.md` entry appended at EOF (append-only)
