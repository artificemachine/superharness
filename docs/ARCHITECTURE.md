# superharness Architecture

## Runtime Layers

superharness is split into four operational layers:

1. `protocol/`
- Canonical cross-agent rules and templates.
- Source of truth for lifecycle and handoff expectations.

2. `engine/`
- Ruby runtime for structured YAML operations.
- Queue transitions (`engine/inbox.rb`), contract queries (`engine/contract.rb`), and hygiene validation (`engine/validate.rb`).

3. `cli/`
- Primary user-facing shell commands.
- Delegation, enqueue/dispatch/watch/recover, normalize, hygiene, and init wrappers.

4. `scripts/`
- Backward-compatible shims for legacy entrypoints.
- launchd watcher install/ensure/uninstall.
- shell entrypoint integrity guard.
- stale launched-item recovery helper.

## Project Runtime State

Per-project state is under `.superharness/`:
- `contract.yaml`
- `handoffs/*.yaml`
- `ledger.md`
- `decisions.yaml`
- `failures.yaml`
- `inbox.yaml` (+ optional archive)

## Lifecycle Model

Inbox statuses:
- `pending`
- `launched`
- `running`
- `done`
- `failed`
- `stale`

Dispatch claims only `pending` items and marks them `launched`.

## Integration Surface

- Claude plugin and hooks live under `adapters/claude-code/`.
- Codex adapter templates live under `adapters/codex-cli/`.
- macOS background watcher automation uses launchd via `scripts/install-launchd-inbox-watcher.sh`.
