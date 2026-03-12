# Compatibility Shims Scope (Phase 0)

## Purpose
Define which legacy entrypoints must remain callable while the runtime is migrated toward `engine/` and `cli/`.

This scope prevents breaking existing user workflows, docs snippets, and automation scripts.

## Backward-Compatible Entrypoints (Required)

These paths must continue to exist and be executable through the refactor:

- `init-project.sh`
- `scripts/delegate-to-claude.sh`
- `scripts/delegate-to-codex.sh`
- `scripts/inbox-enqueue.sh`
- `scripts/inbox-dispatch.sh`
- `scripts/inbox-watch.sh`
- `scripts/inbox-normalize.sh`
- `scripts/check-contract-hygiene.sh`
- `scripts/install-launchd-inbox-watcher.sh`
- `scripts/ensure-launchd-inbox-watcher.sh`
- `scripts/uninstall-launchd-inbox-watcher.sh`
- `scripts/install-git-hooks.sh`
- `adapters/claude-code/install.sh`

## Compatibility Contract

For each required entrypoint:

1. `--help` must return exit code `0`.
2. Existing option names must remain valid.
3. Existing output mode semantics (`--print-only`, `--non-interactive`, etc.) must remain unchanged.
4. If implementation moves, legacy path becomes a shim wrapper to the new location.

## Allowed Internal Changes

- Moving core logic into Ruby modules under `engine/`.
- Moving operational shells under `cli/`.
- Replacing duplicated shell logic with shared helpers.

## Not Allowed During Migration

- Deleting legacy entrypoints listed above.
- Renaming flags without compatibility aliases.
- Silent behavior changes in user-facing commands.

## Removal Policy

Legacy shims may be removed only after:

1. One full minor release cycle with deprecation warnings.
2. README examples fully migrated.
3. Tests updated to target new paths and explicit migration notes published.
