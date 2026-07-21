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

## Exception-handling policy

`except Exception` is allowed, but only at a genuine supervisory boundary —
a place whose whole job is "this must not crash the caller" (a watcher tick,
a dashboard request handler, a best-effort cleanup step). Two rules:

1. **A supervisory `except Exception` must log with `exc_info=True`.**
   Swallowing an error without a traceback is how a scanner, a watcher tick,
   or a dispatch step goes silently dead while still reporting "success" —
   the exact "dead scanner" bug class this project has hit before. Bare
   `pass`, a `print()` with no logger, or a logger call missing `exc_info`
   are all non-compliant. Minimum shape:
   ```python
   except Exception as e:
       logger.warning("<context>: unexpected error: %s", e, exc_info=True)
   ```
   `exc_info=True` works even on a bare `except Exception:` with no bound
   name — it reads the live exception off `sys.exc_info()`, not the bound
   variable — so there is never a reason to skip it for lack of a name.

2. **Prefer a narrow except over a broad one when the failure mode is
   actually known.** If a block can only realistically raise `OSError`,
   `sqlite3.Error`, `json.JSONDecodeError`, etc., catch that, not
   `Exception` — a broad catch there hides bugs instead of guarding against
   real uncertainty. Reach for `except Exception` only when the code inside
   is calling into something genuinely unpredictable (a subprocess, a
   plugin, third-party parsing) and the caller must survive regardless of
   what goes wrong.

`tests/contract/test_source_ratchets.py::test_broad_except_does_not_grow`
enforces the repo-wide `except Exception` count never grows, and
`test_supervisory_excepts_log_with_exc_info` enforces rule 1 for the three
files with the highest historical concentration
(`commands/inbox_watch.py`, `scripts/dashboard-ui.py`,
`commands/inbox_dispatch.py`) — every `except Exception` in those three
files must satisfy rule 1, not just new ones.

## Running the full quality pipeline

```bash
shipguard scan .           # SAST + secrets
pytest tests/ -q           # full suite
superharness demo          # smoke test
```
