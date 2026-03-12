# Consensus Watcher Reliability Report

- Task: `consensus-watcher-reliability-20260311`
- Contract: `v08-reliability`
- Date: `2026-03-11`
- Target repo: `/Users/airm2max/DevOpsSec/superharness`
- Status: `done`
- Consensus verdict: `changes requested`

## Summary

Reviewed the three watcher reliability fixes described in the approved handoff.

One fix is solid: excluding `.superharness/` from the dirty-worktree check stops
the watcher from pausing itself because of its own protocol-state churn.

Two fixes should not ship as currently implemented:

1. `KeepAlive true` in the launchd plist is incorrect for the current watcher shape.
   `scripts/inbox-watch.sh` runs one cycle and exits unless `--foreground` is set,
   while the plist still uses `StartInterval`. With `KeepAlive true`, launchd will
   immediately relaunch the job after a successful exit instead of waiting for the
   configured interval.
2. `sync_worker_copy` in `scripts/inbox-watch.sh` is not safe as written.
   A local `rsync` reproduction showed that syncing the source repo into the worker
   replaces the worker `.superharness` symlink with a copied directory, so source
   and worker protocol state can drift apart after the first sync.

## Findings

1. Accepted: dirty-worktree exclusion.
   - `git -C /Users/airm2max/DevOpsSec/superharness status --porcelain --untracked-files=normal -- ':!.superharness/'` produced no output while plain `git status --porcelain --untracked-files=normal` still showed the current `.superharness` inbox/lock dirt.
   - This matches the intended behavior: ignore harness self-writes, not real source changes.
2. Rejected: `KeepAlive true` on the launchd job.
   - The installed plist invokes `scripts/inbox-watch.sh` without `--foreground`.
   - The script's non-foreground path executes a single `run_cycle` and exits.
   - That makes unconditional `KeepAlive true` a hot-loop trigger rather than a crash-recovery mechanism.
3. Rejected: current worker sync implementation.
   - `scripts/setup-watcher-worker.sh` creates the worker with `.superharness` excluded from the copy and then symlinks worker `.superharness` back to the source project.
   - `scripts/inbox-watch.sh` now rsyncs the source repo into the worker while excluding only `.git` and `.superharness/inbox.yaml`.
   - Reproducing that rsync locally showed the worker `.superharness` symlink being replaced with a real directory, which breaks the original shared-state design.

## Validation

- Ran:
  `pytest -q tests/unit/test_install_scripts.py tests/unit/test_inbox_watch_lock.py tests/integration/test_codex_watcher_pipeline.py tests/integration/test_claude_watcher_pipeline.py`
- Result: `19 passed in 9.02s`

These tests do not currently cover the two regressions above, so the review result
is based on direct code-path analysis plus a local rsync reproduction.

## Next Actions

1. Replace unconditional `KeepAlive true` with a crash-only restart strategy that
   respects the existing `StartInterval`, or move launchd to a true long-running
   foreground watcher mode before enabling unconditional KeepAlive.
2. Rework `sync_worker_copy` to preserve the worker `.superharness` symlink and
   align its exclude list with `scripts/setup-watcher-worker.sh`.
3. Add tests for both behaviors before re-reviewing these reliability fixes.
