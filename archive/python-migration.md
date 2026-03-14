# Python Migration Plan — superharness

**Goal:** Migrate superharness from Bash+Ruby to Python-only, gaining cross-platform portability (macOS, Linux, Windows) and a single-language codebase.

**Approach:** Iterative, bottom-up, **test-driven (TDD)**. Each iteration is independently shippable — the project stays functional after every iteration. No big-bang rewrite.

**TDD discipline:** For every module ported, tests are written **before** the implementation. The cycle is always: Red → Green → Refactor. No production code without a failing test first.

---

## TDD Workflow (applies to every iteration)

1. **Capture current behavior** — run the existing shell/Ruby code against known inputs, record outputs as golden fixtures (`tests/fixtures/`)
2. **Write failing tests first** — pytest tests that assert the expected behavior of the new Python module (imports fail → Red)
3. **Implement minimal code** — just enough to make the tests pass (→ Green)
4. **Refactor** — clean up, extract helpers, improve naming (tests still pass → Green)
5. **Parity check** — run golden fixtures through both old and new code, diff outputs. Zero diff = done.
6. **Delete old code** — remove the shell/Ruby file only after all tests pass and parity is confirmed

Test categories per module:
- **Unit tests** — isolated function behavior, edge cases, error paths
- **Integration tests** — module interactions (e.g., engine writes YAML, CLI reads it)
- **Parity tests** — old vs new output comparison (temporary, removed after migration)

---

## Iteration 0 — Foundation (scaffolding)

**What:** Set up Python package structure and CLI entrypoint alongside existing shell scripts.

**Tests first:**
- `tests/unit/test_cli_router.py` — test that each subcommand (init, delegate, task, watch, ...) is recognized and routed
- `tests/unit/test_cli_unknown.py` — test that unknown subcommands produce helpful error messages
- `tests/integration/test_cli_passthrough.py` — test that CLI pass-through to shell scripts produces identical output

**Then implement:**
- Create `src/superharness/` package with `__init__.py`, `__main__.py`
- Add `pyproject.toml` with `[project.scripts] superharness = "superharness.cli:main"`
- Add `click` (or `argparse`) CLI router that mirrors current `superharness` wrapper subcommands
- CLI initially delegates to existing shell scripts via `subprocess` (pass-through)
- Add `pip install -e .` dev install so `superharness` resolves to the Python entrypoint

**Result:** Python CLI wrapper exists. All logic still in Bash/Ruby. Nothing breaks.

---

## Iteration 1 — Kill Ruby: YAML engine in Python

**What:** Replace all 7 Ruby engine files with Python equivalents using `ruamel.yaml` (round-trip preserving).

**Tests first (per module):**

For each Ruby file, before writing any Python:

1. **Golden fixtures** — capture Ruby outputs for representative inputs:
   - `tests/fixtures/contract/` — sample contract.yaml files + expected parse results
   - `tests/fixtures/inbox/` — inbox state transitions (pending→launched→done→failed→stale)
   - `tests/fixtures/discussion/` — round creation, position submission, consensus
2. **Unit tests:**
   - `tests/unit/test_engine_contract.py` — parse tasks, extract IDs, read acceptance criteria, update status, find latest handoff
   - `tests/unit/test_engine_inbox.py` — enqueue, dequeue, transition states, retry logic, stale detection
   - `tests/unit/test_engine_discussion.py` — create round, submit position, check consensus, archive
   - `tests/unit/test_engine_validate.py` — schema validation, required fields, type checks
   - `tests/unit/test_yaml_helpers.py` — round-trip load/dump preserves comments and ordering
3. **Parity tests:**
   - `tests/parity/test_ruby_python_contract.py` — feed same YAML to Ruby and Python, assert identical output
   - Same for inbox, discussion

**Then implement:**
- `src/superharness/engine/contract.py`
- `src/superharness/engine/inbox.py`
- `src/superharness/engine/discussion.py`
- `src/superharness/engine/validate.py`
- `src/superharness/engine/yaml_helpers.py`
- Update shell scripts to call `python3 -m superharness.engine.*` instead of `ruby engine/*.rb`

**Then delete:** Ruby files only after parity tests confirm zero diff.

**Result:** Ruby dependency eliminated. `doctor.sh` no longer checks for Ruby.

**Subsumes contract task:** `unify-yaml-parser` (done as side effect).

---

## Iteration 2 — Core scripts → Python modules

**What:** Port the high-traffic scripts that do real logic (not just routing).

**TDD approach per script** (one at a time, in order):

### 2a. `inbox-dispatch.sh` → `src/superharness/commands/inbox_dispatch.py`

**Tests first:**
- `test_dispatch_dequeue.py` — picks next pending item, transitions to launched
- `test_dispatch_timeout.py` — kills subprocess after timeout, marks failed
- `test_dispatch_lock.py` — acquires lock, rejects concurrent dispatch, releases on exit
- `test_dispatch_retry.py` — failed item with retries_left > 0 re-enqueues as pending
- `test_dispatch_state_reconcile.py` — launched item that finished updates to done/failed

### 2b. `inbox-watch.sh` → `src/superharness/commands/inbox_watch.py`

**Tests first:**
- `test_watch_poll_cycle.py` — detects pending items, calls dispatch
- `test_watch_stale_recovery.py` — detects items stuck in launched, triggers recovery
- `test_watch_worker_sync.py` — syncs worker directory, excludes .superharness/.git
- `test_watch_single_cycle.py` — `--once` flag runs one cycle and exits (for cron)

### 2c. `delegate.sh` → `src/superharness/commands/delegate.py`

**Tests first:**
- `test_delegate_prompt_assembly.py` — builds prompt from contract + handoffs + discussions
- `test_delegate_claude_launch.py` — spawns claude with correct flags (mock subprocess)
- `test_delegate_codex_launch.py` — spawns codex with --full-auto when non-interactive
- `test_delegate_confirmation_gate.py` — interactive mode requires confirmation

### 2d. `task.sh` → `src/superharness/commands/task.py`

**Tests first:**
- `test_task_create.py` — creates task in contract with required fields
- `test_task_status.py` — updates task status, validates transitions
- `test_task_delete.py` — removes task from contract
- `test_task_acceptance_criteria.py` — reads/writes acceptance criteria

### 2e. `discuss.sh` → `src/superharness/commands/discuss.py`

**Tests first:**
- `test_discuss_enqueue.py` — creates discussion directory and state.yaml
- `test_discuss_round_dispatch.py` — dispatches round when all positions submitted
- `test_discuss_consensus.py` — detects agreement/disagreement across positions

### 2f. `inbox-enqueue.sh` → `src/superharness/commands/inbox_enqueue.py`

**Tests first:**
- `test_enqueue_adds_row.py` — appends item to inbox.yaml with correct fields
- `test_enqueue_duplicate.py` — rejects duplicate task_id+target combination
- `test_enqueue_priority.py` — respects priority ordering

**Each script:** write tests → implement → parity check → delete `.sh` file.

**Result:** Core logic is Python. Remaining shell scripts are thin utilities.

---

## Iteration 3 — Utility scripts → Python

**What:** Port the remaining utility/install scripts.

**Tests first (grouped by function):**

**Status & monitoring:**
- `test_contract_today.py` — table output, next-task suggestion, owner filtering
- `test_status.py` — watcher health, inbox queue depth, discussion state
- `test_notify.py` — cooldown logic, duplicate suppression

**Inbox utilities:**
- `test_inbox_normalize.py` — archives completed rows, preserves pending
- `test_inbox_recover_stale.py` — marks stale items, respects retry limits
- `test_inbox_deadline_check.py` — deadline_exceeded marking

**Health & validation:**
- `test_doctor.py` — checks python3, git, claude/codex presence; exit codes
- `test_check_contract_hygiene.py` — validates contract structure
- `test_check_changelog_append_only.py` — detects non-append edits

**Setup:**
- `test_init_project.py` — creates .superharness/ with correct files
- `test_setup_watcher_worker.py` — creates worker clone, excludes correct dirs

**Then implement and delete `.sh` files one by one.**

**Result:** All `scripts/*.sh` eliminated.

---

## Iteration 4 — Platform backends (cross-platform service install)

**What:** Replace macOS-only launchd scripts with platform-abstracted service management.

**Tests first:**
- `tests/unit/test_platform_base.py` — abstract interface contract (install, uninstall, status, is_running)
- `tests/unit/test_platform_macos.py` — plist generation matches expected XML, launchctl commands correct
- `tests/unit/test_platform_linux.py` — systemd unit file generation, systemctl commands correct
- `tests/unit/test_platform_windows.py` — schtasks XML generation, correct command assembly
- `tests/unit/test_platform_detect.py` — auto-detection picks correct backend per OS
- `tests/integration/test_install_watcher.py` — end-to-end install/uninstall on current platform (CI matrix)

**Then implement:**
- `src/superharness/platform/base.py` — abstract interface
- `src/superharness/platform/macos.py` — launchd backend
- `src/superharness/platform/linux.py` — systemd backend
- `src/superharness/platform/windows.py` — Task Scheduler backend
- CLI: `superharness install-watcher` auto-detects platform

**Delete:** `install-launchd-inbox-watcher.sh`, `uninstall-launchd-inbox-watcher.sh`, `ensure-launchd-inbox-watcher.sh`

**Result:** `superharness install-watcher` works on macOS, Linux, and Windows.

---

## Iteration 5 — Hooks as thin shims

**What:** Claude Code hooks must stay as `.sh` files (hook system requirement), but reduce them to 1-3 line shims.

```bash
#!/bin/bash
exec python3 -m superharness.hooks.session_start "$@"
```

**Tests first:**
- `tests/unit/test_hook_session_start.py` — JSON output format, contract injection, watcher check
- `tests/unit/test_hook_branch_guard.py` — blocks force push, blocks push to main/master
- `tests/unit/test_hook_scope_guard.py` — blocks .env writes, warns on system files
- `tests/unit/test_hook_ledger_append.py` — appends correct entries to ledger.md
- `tests/integration/test_hook_shim.py` — shell shim invokes Python module, output matches

**Then implement:**
- `src/superharness/hooks/session_start.py`
- `src/superharness/hooks/branch_guard.py`
- `src/superharness/hooks/scope_guard.py`
- `src/superharness/hooks/ledger_append.py`
- Replace hook `.sh` bodies with `exec python3 -m ...`

**Result:** Hook logic is Python. Shell files are vestigial shims only.

---

## Iteration 6 — Cleanup and packaging

**What:** Final cleanup pass.

**Tests first:**
- `tests/integration/test_full_lifecycle.py` — init → create task → delegate → dispatch → complete → ledger entry (end-to-end, pure Python)
- `tests/integration/test_cross_platform.py` — critical paths work on macOS + Linux (CI matrix)
- `tests/unit/test_doctor_python_only.py` — doctor checks Python ≥3.10, no Ruby check

**Then:**
- Remove `engine/` Ruby directory entirely
- Remove all `scripts/*.sh` files (replaced by Python)
- Remove all `tests/parity/` (no longer needed)
- Update `superharness` entrypoint: keep as shell shim (`exec python3 -m superharness "$@"`) or rely on pip-installed command
- Update `doctor` to check Python ≥3.10, `pip`, no longer Ruby
- Update `CLAUDE.md` project description: "Python CLI" instead of "Shell scripts + Python tests"
- Update CI workflows
- Tag `v1.0.0` — Python-only release

**Result:** Single-language Python project. Cross-platform. No Ruby, no Bash logic.

---

## Dependencies to add

```
ruamel.yaml    # round-trip YAML (replaces Ruby Psych)
click          # CLI framework (optional, argparse works too)
filelock       # cross-platform file locking
```

All pure Python, no native extensions. Works on macOS/Linux/Windows without compilation.

---

## Test infrastructure

```
tests/
├── fixtures/           # Golden input/output files for parity testing
│   ├── contract/       # Sample contract.yaml files
│   ├── inbox/          # Sample inbox states
│   └── discussion/     # Sample discussion rounds
├── parity/             # Old-vs-new output comparison (temporary, removed in Iter 6)
├── unit/               # Isolated function tests
├── integration/        # Module interaction tests
└── e2e/                # Full lifecycle tests
```

**Coverage target:** ≥90% line coverage on all new Python code. Measured per iteration, enforced in CI.

---

## What each iteration unblocks

| Iteration | Eliminates | Enables |
|---|---|---|
| 0 | — | Python CLI entrypoint, test infrastructure |
| 1 | Ruby | Single YAML engine, `unify-yaml-parser` done |
| 2 | Most Bash | Core logic testable without shell |
| 3 | All `scripts/*.sh` | No Bash logic remaining |
| 4 | macOS-only service install | Linux + Windows watcher support |
| 5 | Bash hook logic | Hooks testable in pytest |
| 6 | All shell artifacts | Clean `v1.0.0` release |

---

## Existing contract tasks affected

- `unify-yaml-parser` → absorbed by Iteration 1
- `structured-error-logging` → natural in Python (logging module), absorbed by Iterations 2-3
- `eliminate-cli-shim-layer` → absorbed by Iteration 0
- `ci-hook-test-coverage` → easier after Iteration 5 (hooks are Python, testable with pytest)

---

## Risk notes

- **Iteration 1 is the riskiest** — Ruby engine is the brain. Parity tests are the safety net: run same YAML through Ruby and Python, assert identical output before deleting Ruby.
- **Iteration 2 changes the locking model** — concurrent dispatch tests with `filelock` must cover: lock contention, stale lock cleanup, cross-process locking.
- **Windows support is Iteration 4+** — don't promise it before then.
- Each iteration should have its own branch, PR, and test pass before merge.
- **TDD discipline is non-negotiable** — no PR merges without tests written before implementation. CI enforces ≥90% coverage on new code.
