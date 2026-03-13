# Contributing to superharness

## Running tests

```bash
pytest tests/ -q
```

Requires Python 3.11+, Bash 4+, Ruby, and `shellcheck`. Install Python deps with `uv sync --dev`.

## Commit conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `test:` — adding or updating tests
- `chore:` — maintenance, deps, CI

## PR expectations

1. All `pytest tests/ -q` tests must pass.
2. Shell scripts must pass the entrypoint guard: `bash scripts/check-shell-entrypoints.sh --staged` (run automatically by pre-commit).
3. A `CHANGELOG.md` entry must be appended at EOF (append-only — never edit existing lines).
4. `shellcheck scripts/*.sh adapters/**/*.sh` must be clean.

## Adding a new CLI command

1. Create `cli/<cmd>.sh` with `set -euo pipefail` and a `--help` guard.
2. Add a dispatch entry in `superharness` (the top-level shell dispatcher).
3. Add the script path to `ENTRYPOINT_FILES` in `scripts/check-shell-entrypoints.sh`.
4. Add a `pytest` test in `tests/unit/` or `tests/integration/`.

## CHANGELOG policy

`CHANGELOG.md` is append-only. Add new entries at EOF only. Never reorder, edit, or delete existing lines.

## Dependencies

Core runtime: Bash 4+, Ruby, Python 3.9+. Do not introduce new runtime dependencies without opening an issue for discussion first.

## Reporting issues

Open a GitHub issue with steps to reproduce, output of `superharness doctor`, and your platform/shell version.
