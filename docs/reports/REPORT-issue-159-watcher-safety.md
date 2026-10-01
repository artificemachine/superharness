# Issue #159 watcher safety

Status: shipping authorized by the operator; release-candidate tag selected. No final release or package-index publication is selected.

## Provenance

Worktree branch: fix/watcher-worker-source-overlap, based on origin/main 9efe2fee. PR #158 head 249b95fd was conflicting. Its scoped source and regression changes were ported without merging or cherry-picking. Protected instruction files and the original dirty checkout were untouched.

## Changes

Worker sync resolves both roots and rejects equal, nested, ancestor, and symlink-alias destinations before mkdir or mutation. Generated-artifact pruning independently validates the source root. Python copying replaces destination file and directory symlinks before writing. Watcher setup rejects project overlap and any overlap with resolved source state; stale state deletion is fenced to the dedicated worker root. Dashboard defaults use dedicated workers and explicit uncreated configured paths are honored.

## Verification

Command: PYTHONPATH=src uv run --no-sync pytest tests/unit/test_watcher_worker_guard.py tests/unit/test_dashboard_watcher_default.py tests/unit/test_cross_platform_baseline.py -q --tb=short

UV_PROJECT_ENVIRONMENT was set to the existing repo-local virtual environment.

Isolated initial RED: 18 failed, 25 passed in 0.96s. Directory symlink RED: SameFileError, 1 failed in 0.20s. File symlink RED: protected source changed from keep to fresh, 1 failed in 0.16s. Source-state symlink RED: Too many levels of symbolic links, 1 failed in 0.24s. Nested external source-state worker RED: DID NOT RAISE SystemExit, 1 failed in 0.19s. Final focused GREEN: 49 passed in 0.60s. Full-suite verification is handled independently by the orchestrator.

Independent orchestrator verification passed all 49 focused tests in 0.35s; the worker repeated them after formatting. Final read-only safety review found no remaining blockers.

Final full-suite command: PYTHONPATH=src uv run --no-sync pytest tests/ -q --tb=short, using the existing repo-local environment. Run 69803 exited 0: 5868 passed, 22 skipped, 5 deselected, 2 xfailed in 595.98s. This is one completed full-suite observation; focused safety results were reproduced. Provider smoke tests were skipped without RUN_PROVIDER_SMOKE=1; the SDK test was skipped because claude_agent_sdk is absent. Two dispatch safety guards remain expected failures. The suite includes HTTP dashboard integration tests.

## Test isolation incident

The first RED run ported upstream regression tests before adding service-install mocks. They unexpectedly invoked launchd and created com.superharness.inbox.container, com.superharness.inbox.random-worker, and com.superharness.inbox.nested-worker. This was reported immediately. The owner approved cleanup; the orchestrator unloaded those labels and deleted exactly their three generated plists. Logs were retained. All watcher regression tests now automatically mock service installation and runtime probing/persistence. Subsequent runs did not intentionally invoke services. The initial uv setup changed this worktree uv.lock; that change was restored from HEAD.

## Delegation

Jev advisory question: Use sequential work or subagents for this bounded watcher safety fix? Choice: subagents; confidence 0.84, agreement. Requested runtime default gpt-5.6-terra was unavailable through the spawn API; inherited model retained rather than inventing a route.

One writer owned all implementation files; an independent read-only reviewer used the configured final-review tier, gpt-6-astra. The orchestrator repeated the focused verification. Estimated dispatch inputs: S=20k, c=1, n=1, k=8k, t=6, W=25k. The skill's input-token model gives sequential 144k versus delegated 214k, with a 37.5k break-even context. These are estimates, not measured usage or a bill; price is unknown. Delegation followed the owner's explicit request. Review found three alias gaps, requiring additional worker turns beyond that initial estimate.

An earlier full-suite attempt was interrupted after the final source-state guard changed: 773 passed, 10 skipped, 5 deselected in 113.59s before SIGINT; no failure observed, not a full-suite pass. The completed run above verified the final source.

## Candidate shipping checks

Selected tag: v1.86.5-rc.1; Python package version: 1.86.5rc1. Package metadata and uv.lock agree. The tag does not trigger publication; a published GitHub release would trigger publish.yml and is outside this shipment.

ShipGuard: zero findings across 1016 files and 59 rules. Candidate-focused safety and release tests: 64 passed in 1.46s. Both sdist and wheel built offline; the wheel was installed into a separate temporary environment and its demo passed with that environment first on PATH and no PYTHONPATH. The candidate uses existing dependency declarations; no dependency was added.

README, documentation placement, changed-symbol coverage, CI governance, append-only changelog, and sensitive-file checks have no blocking findings. Existing coverage configuration has a floor of 56 and no branch coverage: warnings, with actual coverage unknown. Orphan audit reports missing reaper configuration and uncertain process ownership; no host cleanup is part of shipping. The isolated worktree contains no offline report-freshness scripts. Original staged instruction/scaffold changes are excluded.

The initial candidate commit is 201eccc5. Its pre-commit hooks passed 914 tests with 9 skips and a zero-finding staged security scan. PR #158's previous head 249b95fd is integrated as an ancestor so the existing remote branch can be updated without a force push. Conflict resolution retains the candidate source and corrected tests; previous handoff and append-only changelog history are retained. The installed release-advice helper does not recognize the PEP 440 RC metadata as a version source; package metadata and the equivalent SemVer tag were independently verified using packaging.version.Version.
