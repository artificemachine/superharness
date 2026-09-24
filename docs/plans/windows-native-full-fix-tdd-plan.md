# Native Windows Full Fix Plan (TDD by Iteration)

## Iteration 0: Scope + Test Harness Baseline
- Goal: lock target behavior for native Windows (PowerShell/CMD), macOS, and Linux.
- RED:
  - Add failing cross-platform contract tests for watcher, dispatch, delegate, lock handling, and temp file behavior.
- GREEN:
  - Add test fixtures/helpers for OS simulation and temp workspace bootstrapping.
- REFACTOR:
  - Unify platform test utilities in `tests/helpers.py`.
- Exit criteria:
  - Current Windows breakages are reproducible in tests.

## Iteration 1: Platform Runtime Abstraction
- Goal: remove Bash assumptions from core runtime paths.
- RED:
  - Add tests that fail when commands are built with shell-specific wrappers (`bash`, `script`, launchd-only paths).
- GREEN:
  - Introduce a Python `platform_runtime` module for command building, temp files, lock paths, env resolution, and process launch.
- REFACTOR:
  - Route `watch`, `dispatch`, and `delegate` through the abstraction.
- Exit criteria:
  - No core command requires Bash on Windows.

## Iteration 2: Watcher Loop Fully Python-Native
- Goal: make watcher lock/heartbeat/dispatch cycle OS-agnostic.
- RED:
  - Failing tests for stale lock recovery, heartbeat updates, and single-instance guarantees on Windows.
- GREEN:
  - Replace watcher shell path with a Python-only cycle, including lock lifecycle and heartbeat writes.
- REFACTOR:
  - Consolidate lock semantics and stale-lock detection into one shared module.
- Exit criteria:
  - Watcher cycle passes unit and integration tests under Windows simulation.

## Iteration 3: Dispatcher + Delegate Launch Path
- Goal: remove PTY/shell-wrapper dependencies from dispatcher.
- RED:
  - Failing tests for launcher execution without `script`/TTY/Bash.
- GREEN:
  - Implement pure Python subprocess launch and logging with safe non-interactive behavior and explicit env-based confirmation controls.
- REFACTOR:
  - Standardize retry/failure transitions and reconcile paths.
- Exit criteria:
  - Dispatch/delegate succeed on native Windows without shell shims.

## Iteration 4: Service Installation Per OS
- Goal: first-class service management for macOS/Linux/Windows.
- RED:
  - Installer-selection tests fail on Windows (no launchd support).
- GREEN:
  - Add Windows service mode (Task Scheduler startup + interval mode), while retaining launchd/systemd support.
- REFACTOR:
  - Single installer entrypoint selects backend by OS.
- Exit criteria:
  - `watcher-worker` can install/start/verify service on Windows.

## Iteration 5: Python Runtime Pinning + Import Safety
- Goal: eliminate interpreter mismatch bugs (`yaml`/module import failures).
- RED:
  - Failing tests when default `python` lacks required package/module.
- GREEN:
  - Enforce runtime probe against required modules (for example `superharness.engine.inbox`), support explicit override, and persist chosen runtime in service config.
- REFACTOR:
  - Centralize runtime resolution logic.
- Exit criteria:
  - Watcher/dispatch run with deterministic interpreter across OSes.

## Iteration 6: Docs + UX + Guardrails
- Goal: align docs and CLI messaging with actual platform support.
- RED:
  - Docs/CLI consistency tests fail (claims vs behavior).
- GREEN:
  - Update README/GUIDE/INSTALL and `--help` output for native Windows flow.
- REFACTOR:
  - Add docs-lint/check for platform statements.
- Exit criteria:
  - No mixed messaging; Windows instructions are copy-paste valid.

## Iteration 7: End-to-End Matrix + Release Gate
- Goal: prove behavior in CI across supported OSes.
- RED:
  - Add failing GitHub Actions matrix tests (`ubuntu-latest`, `macos-latest`, `windows-latest`) for `init -> watch -> enqueue -> dispatch -> status`.
- GREEN:
  - Fix remaining cross-platform defects until matrix passes.
- REFACTOR:
  - Split slow e2e jobs and add caching to keep CI practical.
- Exit criteria:
  - All OS matrix jobs pass; feature is release-ready.

