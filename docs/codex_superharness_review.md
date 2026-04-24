# Codex Superharness Review

**Verdict:** Changes Requested

This project has a strong core idea and a useful feature set, but the current architecture is overextended and the project state is actively broken.

## Critical

- `.superharness/contract.yaml:1959` has `decisions: []` / `failures: []`, then `.superharness/contract.yaml:1961` starts another task at root level. That makes the contract invalid YAML. `python -m superharness contract --project .` currently fails to parse the contract.
- `src/superharness/commands/daemon.py:100` starts `python -m superharness.commands.watch`, but that module does not exist. The actual CLI `watch` command routes to `superharness.commands.inbox_watch`. Result: `shux daemon start` can claim a daemon started while the process exits immediately.

## Major

- `src/superharness/commands/daemon.py:23` and `src/superharness/engine/operator.py:94` both write `.superharness/daemon.pid.json`, but with incompatible schemas. Daemon expects `pid`; operator writes `operator_pid` and `dashboard_port`. `src/superharness/cli.py:284` then also reads that same file for dashboard discovery. This state file needs one owner or a versioned schema.
- `src/superharness/commands/auto_dispatch.py:45` calls `classify_task(task, project_dir=project_dir)`, but `src/superharness/engine/model_router.py:57` expects `title`, `criteria`, `files`, and `previously_failed`. The exception is swallowed at `src/superharness/commands/auto_dispatch.py:49`, so auto-dispatch silently falls back to `claude-code/standard`.
- `src/superharness/engine/schemas.py:28` is missing lifecycle statuses that `src/superharness/engine/next_action.py:18` treats as canonical, including `pending_user_approval`, `review_requested`, `review_failed`, and `stopped`. The schemas are not the source of truth.
- `src/superharness/engine/validate.py:98` loads the contract without schema validation, despite `src/superharness/engine/yaml_helpers.py:30` supporting it. That undercuts the Pydantic protocol-model architecture.
- `src/superharness/engine/inbox.py:179` fails open on dependency-read errors. If the contract is malformed, dependency checks can return satisfied instead of blocking dispatch.

## Architecture Notes

- Strength: file-native protocol, append-only handoff/ledger design, adapter manifests, and explicit task lifecycle are the right primitives for this product.
- Strength: test surface is substantial: 162 test files and 1334 test/class definitions were counted during review.
- Weakness: lifecycle state is duplicated across schemas, dashboard UI, adapter payload, delegate gates, task commands, and docs. `next_action.py` is labeled the core heart, but it has not fully become the canonical source.
- Weakness: feature scope is now broad: task lifecycle, dashboard, daemon, operator, auto-dispatch, model routing, cost tracking, modules, packs, discussions, worktrees, notifications, and adapters. The product needs consolidation more than more features.
- Hygiene issue: runtime files are leaking into git state. Current status showed `.superharness/daemon.pid.json`, `.superharness/trace.jsonl`, and `.superharness/inbox.yaml.lock.d/`, but `.superharness/.gitignore:8` does not ignore those despite docs claiming runtime files are excluded.

## Next Fix Order

1. Fix `.superharness/contract.yaml` corruption first.
2. Fix daemon start target to `superharness.commands.inbox_watch` and add a real daemon-start regression test.
3. Unify lifecycle statuses between `next_action.py`, `schemas.py`, dashboard, and command gates.
4. Make protocol reads validate against schema on command boundaries.
5. Split `daemon.pid.json` into `daemon-state.json` and `operator-state.json`, or define one versioned runtime-state schema.

## Verification

The test suite was not run because project instructions require confirmation before tests.
