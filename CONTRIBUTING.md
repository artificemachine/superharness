# Contributing to superharness

## Quick start

```bash
git clone https://github.com/celstnblacc/superharness.git
cd superharness
pip install -e ".[dev]"   # or: uv sync --dev
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

## Protocol state

Files under `.superharness/` are operational state — do not modify them in PRs unless the change is specifically about protocol data migration.

## Running the full quality pipeline

```bash
shipguard scan .           # SAST + secrets
pytest tests/ -q           # 942 tests
superharness demo          # smoke test
```
