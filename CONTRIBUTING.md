# Contributing to superharness

## Quick start

```bash
git clone https://github.com/artificemachine/superharness.git
cd superharness
uv sync --dev             # dev deps live in [dependency-groups] (PEP 735)
pytest tests/ -q          # all tests must pass
```

## Making changes

1. Create a branch: `git checkout -b feat/your-feature`
2. Write a failing test first (TDD) — see `tests/unit/` for examples
3. Implement the fix or feature
4. Run `pytest tests/ -q` and `shipguard scan .` — both must pass
5. Open a PR against `main`

## Code conventions

- Python 3.11+ only; type hints on public functions
- Keep CLI modules in `src/superharness/commands/`
- Engine logic (no I/O) in `src/superharness/engine/`
- New CLI commands need at least one unit test that invokes the command via subprocess

## Regression tests

When a fix lands for a real bug (not a new feature), tag its test `@pytest.mark.regression` and cite the bug in the docstring (what broke, why it wasn't caught). This is a forward-looking convention adopted 2026-07-21 — CHANGELOG.md has hundreds of prior `fix:` entries with no discoverable regression coverage, and retagging all of them retroactively isn't realistic. Going forward, `pytest -m regression` should answer "is bug X still covered" without reading history.

## Protocol state

Files under `.superharness/` are operational state — do not modify them in PRs unless the change is specifically about protocol data migration.

## Running the full quality pipeline

```bash
shipguard scan .           # SAST + secrets
pytest tests/ -q           # full suite
superharness demo          # smoke test
```
