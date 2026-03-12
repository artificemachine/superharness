# Contributing to superharness

Thank you for your interest in contributing.

## Getting started

```bash
git clone https://github.com/your-org/superharness
cd superharness
pip install -r requirements.txt
```

Run the test suite:

```bash
pytest tests/ -q
```

## Requirements

- Bash 4+ (scripts are Bash-based)
- Ruby (inbox YAML engine)
- Python 3.9+ with pytest
- `shellcheck` for shell linting

## Submitting changes

1. Fork the repository and create a feature branch.
2. Make your changes. Keep each commit focused on one thing.
3. Run `pytest tests/ -q` — all tests must pass.
4. Run `shellcheck scripts/*.sh adapters/**/*.sh` — no errors.
5. Open a pull request against `main`.

## CHANGELOG policy

`CHANGELOG.md` is **append-only**. Add new entries at the bottom. Never edit, reorder, or delete existing lines.

## Code style

- Shell scripts: `set -euo pipefail`, double-quote variable expansions, `shellcheck`-clean.
- Python: `ruff check` clean; no unused imports or variables.
- Tests: `pytest` with fixtures from `conftest.py`. Prefer direct-import tests over subprocess for coverage instrumentation.

## Protocol changes

Changes to the superharness protocol (contract, handoff, inbox schemas) require:
- Updated YAML templates in `protocol/templates/`
- Updated spec in `protocol/spec.md`
- Updated `docs/ARCHITECTURE.md` if status flows change

## Reporting issues

Open a GitHub issue with steps to reproduce, the output of `superharness doctor`, and your platform/shell version.
