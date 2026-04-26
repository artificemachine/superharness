# Project Handoff: SQLite-Primary Cutover Complete (v1.37.1)

**Date**: 2026-04-26
**Status**: Gate 3 Complete / SQLite-primary live / v1.37.1 on PyPI
**Summary**: Completed the full SQLite-primary cutover (Gate 3). Every read/write path now uses SQLite as the primary store with YAML as fallback. Fixed a cascade of dual-mode fallback bugs, published v1.37.0, then shipped v1.37.1 to correct a version-string mismatch between `pyproject.toml` and `__init__.py`.

---

## What Shipped This Session

### Gate 3: SQLite-Only Cutover (v1.37.0 — PR #140)

The capstone of the SQLite migration. All state read paths now route through `state_reader.py` which honours `STATE_BACKEND` (`yaml_only` / `dual` / `sqlite_only`).

**Key fixes landed:**

- **`state_reader._has_sqlite_db()` guard** — dual mode skips SQLite entirely when `state.sqlite3` doesn't exist yet, preventing an auto-created empty DB from shadowing YAML data.
- **`sqlite_only` without DB** — raises `RuntimeError` so callers fall back to YAML gracefully.
- **`dashboard-ui.py` — `_in_harness` guard** — state_reader calls gated behind `contract_file.parent.name == ".superharness"`, preventing CI from resolving `project_dir` to the repo root and returning real tasks for missing-file tests.
- **`dashboard-ui.py` — direct YAML fallback** — `contract_tasks()`, `board_view()`, `board_tasks()`, `review_queue()` all fall through to direct `contract.yaml` read when state_reader returns empty.
- **`inbox_items()` dual-mode fallback** — falls back to YAML when SQLite returns empty in non-`sqlite_only` mode.
- **`board_tasks()` missing-file guard** — returns `{}` when `raw_tasks` is empty and `contract_file` doesn't exist.
- **`engine/inbox.py` `enqueue()`** — added missing `model_override` and `effort_override` params (inbox_enqueue.py was passing both; the YAML writer wasn't accepting them, causing `TypeError` in auto-dispatch and deadline-check flows).

### Version String Fix (v1.37.1 — PRs #141, #142)

v1.37.0 was published before `__init__.py` was updated, so `superharness --version` reported `1.36.0`. Fixed in two steps:

- **PR #141** — updated `__init__.py` to `"1.37.0"` (no `pyproject.toml` change, so no new release triggered)
- **PR #142** — patch bump to `1.37.1` in both files, triggering auto-release + PyPI publish

---

## Current Version

| | |
|---|---|
| **PyPI** | `1.37.1` |
| **`superharness --version`** | `1.37.1` |
| **Default backend** | `dual` (SQLite first, YAML fallback) |
| **Gate 3** | Complete |

---

## Contract Status

| Task | Status | Owner |
|---|---|---|
| `chore.collapse-guards-next-action` | done | claude-code |
| `verify.auto-dispatch.A/B/C` | done | claude-code |
| `feat.dashboard-auto-restart-on-upgrade` | plan_approved | claude-code |
| `feat.autonomous-peer-review` | todo | gemini-cli |
| `mock.alpha` | report_ready | claude-code |
| `mock.beta` | review_requested | codex-cli |

86 archived tasks hidden (`shux contract --include-archived`).

---

## Next Actions

1. **`feat.dashboard-auto-restart-on-upgrade`** — plan is approved, ready to implement. Dashboard should detect when the installed superharness version changes and auto-restart.
2. **`feat.autonomous-peer-review`** — Gemini peer-reviews Claude's completed tasks autonomously via `report_ready` status.
3. **`mock.alpha` report** — report is ready for operator review (`shux close mock.alpha` after reading the handoff).
4. **`mock.beta`** — review requested, pending codex-cli.

---

## Infrastructure

Start the background stack with:

```bash
shux operator start --port 8787
```

The Guardian self-heals the Watcher and Dashboard if they crash, and arbitrates port conflicts automatically.

**State backend** is `dual` by default. To run sqlite-only:

```bash
STATE_BACKEND=sqlite_only shux status
```
