# Python Migration Plan — TDD with Independent Modules

## Goal

Consolidate superharness from Bash + Ruby + Python to **Python as primary language**.
Keep only minimal Bash for: `superharness` entrypoint wrapper (130 lines), `cli/` routing shims (15 × 5 lines), launchd plist generation, `inbox-watch.sh` loop (279 lines).

**Total porting surface: ~3,838 lines across 12 files (6 Ruby engine modules + 6 Bash scripts) exposing ~45 CLI commands/subcommands.**

## Principles

- **TDD**: write failing tests first, then implement until green
- **Independent modules**: two agents can work in parallel without conflicts
- **No edits to existing files** until swap phase — only new `.py` files
- **Conformance tests**: Ruby and Python must produce identical output during dual-run
- **One commit per green module** for bisectable history

---

## Codebase Inventory (as of main @ 55cc8a3)

### Engine (Ruby)

| File | Lines | Commands | Type |
|------|-------|----------|------|
| `engine/yaml_helpers.rb` | 40 | 0 (lib) | Shared utility |
| `engine/inbox.rb` | 552 | 14 | CLI subcommands |
| `engine/contract.rb` | 156 | 7 | CLI subcommands |
| `engine/validate.rb` | 123 | 1 | Standalone |
| `engine/discuss.rb` | 307 | 2 | CLI subcommands |
| `engine/discussion.rb` | 461 | 12 | CLI subcommands |
| **Engine total** | **1,639** | **36** | |

### Scripts (Bash + inline Ruby)

| File | Lines | Commands | Type |
|------|-------|----------|------|
| `scripts/task.sh` | 383 | 3 | Shell subcommands |
| `scripts/contract-today.sh` | 158 | 1 | Single command |
| `scripts/inbox-dispatch.sh` | 447 | 1 | Single command |
| `scripts/delegate.sh` | 409 | 1 | Single command |
| `scripts/discuss.sh` | 262 | 7 | Shell subcommands |
| `scripts/discussion-dispatch.sh` | 122 | 1 | Single command |
| **Scripts total** | **1,781** | **14** | |

### Already Python (keep as-is)

| File | Lines | Notes |
|------|-------|-------|
| `scripts/monitor-ui.py` | 917 | Monitoring dashboard — no Ruby deps |

### Architecture Layers

```
superharness (130 lines, Bash entrypoint)
  └── cli/*.sh (15 × 5-line shims → exec scripts/*.sh)
        └── scripts/*.sh (Bash orchestrators, call ruby engine/*.rb)
              └── engine/*.rb (Ruby core logic)
```

After migration:
```
superharness (Bash entrypoint — kept)
  └── cli/*.sh → cli/*.py or direct Python (S2)
        └── scripts/*.py (Python, import engine.* directly)
              └── engine/*.py (Python core logic)
```

### Existing Test Coverage

Unit tests (29 files): `test_branch_guard`, `test_changelog_append_only`, `test_contract_hygiene`, `test_delegate`, `test_discuss_approval`, `test_doctor`, `test_engine_contract`, `test_engine_inbox`, `test_engine_validate`, `test_inbox_deadline`, `test_inbox_dispatch`, `test_inbox_enqueue`, `test_inbox_recover`, `test_inbox_watch_lock`, `test_init_project`, `test_install_scripts`, `test_ledger_append`, `test_monitor_ui`, `test_scope_guard`, `test_session_start`, `test_superharness_commands`, `test_task_failed_reason`, `test_uninstall`

Integration tests (6 files): `test_claude_watcher_pipeline`, `test_cli_compatibility_baseline`, `test_codex_watcher_pipeline`, `test_contract_hygiene_ci`, `test_deadline_enforcement_smoke`, `test_shell_guard_integration`

---

## Module Map

| Module | Files Created | Owner | Source Lines | Commands | Depends On |
|--------|-------------|-------|-------------|----------|------------|
| **M0** | `engine/__init__.py`, `engine/yaml_helpers.py`, `tests/unit/test_yaml_helpers_py.py` | any | 40 | 0 (lib) | none |
| **M1** | `engine/inbox.py`, `tests/unit/test_engine_inbox_py.py` | codex-cli | 552 | 14 | M0 |
| **M2** | `engine/contract.py`, `tests/unit/test_engine_contract_py.py` | claude-code | 156 | 7 | M0 |
| **M3** | `engine/validate.py`, `tests/unit/test_engine_validate_py.py` | codex-cli | 123 | 1 | M0 |
| **M4** | `engine/discuss.py`, `tests/unit/test_discuss_approval_py.py` | claude-code | 307 | 2 | M0 |
| **M5** | `engine/discussion.py`, `tests/unit/test_engine_discussion_py.py` | codex-cli | 461 | 12 | M0 |
| **M6** | `scripts/task.py`, `tests/unit/test_task_py.py` | claude-code | 383 | 3 | M2 |
| **M7** | `scripts/contract_today.py`, `tests/unit/test_contract_today_py.py` | codex-cli | 158 | 1 | M2 |
| **M8** | `scripts/inbox_dispatch.py`, `tests/unit/test_inbox_dispatch_py.py` | claude-code | 447 | 1 | M1, M2 |
| **M9** | `scripts/delegate.py`, `tests/unit/test_delegate_py.py` | codex-cli | 409 | 1 | M2, M5 |
| **M10** | `scripts/discuss_cli.py`, `tests/unit/test_discuss_cli_py.py` | claude-code | 262 | 7 | M1, M4, M5 |
| **M11** | `scripts/discussion_dispatch.py`, `tests/unit/test_discussion_dispatch_py.py` | codex-cli | 122 | 1 | M1, M2, M5 |
| **S1** | (swap Bash callers: `ruby` → `python3`) | any | — | — | M1–M5 all green |
| **S2** | (update `superharness` entrypoint + `cli/` routing) | any | — | — | M6–M11 all green |
| **S3** | (delete `.rb` files, remove ruby dep) | any | — | — | S1, S2 |

---

## Dependency Graph

```
M0 (yaml_helpers)
├── M1 (inbox)      ──┐
├── M2 (contract)   ──┼── S1 (swap callers) ── S3 (cleanup)
├── M3 (validate)   ──┤
├── M4 (discuss)    ──┤
└── M5 (discussion) ──┘
        │
        ├── M6  (task)               ──┐
        ├── M7  (contract_today)     ──┤
        ├── M8  (inbox_dispatch)     ──┼── S2 (entrypoint) ── S3
        ├── M9  (delegate)           ──┤
        ├── M10 (discuss_cli)        ──┤
        └── M11 (discussion_dispatch)──┘
```

---

## Parallel Lanes

| Lane A (claude-code) | Lane B (codex-cli) |
|----------------------|-------------------|
| M0 (shared, do first) | (wait for M0) |
| M2 (contract.py) | M1 (inbox.py) |
| M4 (discuss.py) | M3 (validate.py) |
| M6 (task.py) | M5 (discussion.py) |
| M8 (inbox_dispatch.py) | M7 (contract_today.py) |
| M10 (discuss_cli.py) | M9 (delegate.py) |
| — | M11 (discussion_dispatch.py) |

Both lanes run fully in parallel after M0.

### Workload Balance

| Lane | Modules | Total Source Lines | Total Commands |
|------|---------|-------------------|----------------|
| **A (claude-code)** | M2, M4, M6, M8, M10 | 1,555 | 20 |
| **B (codex-cli)** | M1, M3, M5, M7, M9, M11 | 1,825 | 30 |

Lane B is heavier (inbox.rb 552 + discussion.rb 461 are the two largest engine modules). Lane A finishes earlier and can assist with S1/S2 swap phases while B completes M9/M11.

---

## TDD Protocol Per Module

Every module follows the same 4-step cycle:

### Step 1 — RED

Write `tests/unit/test_<name>_py.py` that calls `python3 engine/<name>.py <command> --flags`.
Run → all fail (file doesn't exist yet).

### Step 2 — GREEN

Implement `engine/<name>.py` one command at a time.
After each command: run its specific test → green.

### Step 3 — CONFORM

Add a round-trip conformance test:
- Same input through `ruby engine/<name>.rb` AND `python3 engine/<name>.py`
- Assert identical stdout
- Covers YAML serialization parity (key order, quoting, comments)

### Step 4 — COMMIT

`pytest tests/unit/test_<name>_py.py` → all green → commit.

---

## Module Specs

### M0 — yaml_helpers.py

- Port: `engine/yaml_helpers.rb` (40 lines)
- `safe_load(path, expected_class)` → returns `{}` or `[]` if missing/nil
- `safe_load_normalized(path, expected_class)` → normalizes `datetime` to ISO 8601 strings
- `normalize_scalar_values(obj)` → recursive normalizer for Time/Date → ISO strings
- Uses `yaml.safe_load()` from PyYAML
- Test: round-trip existing `contract.yaml` and `inbox.yaml`

### M1 — inbox.py (codex-cli)

- Port: `engine/inbox.rb` (552 lines, 14 commands)
- Commands: `enqueue`, `next_pending`, `launch`, `set_status`, `set_field`, `approve_dirty_worktree`, `remove`, `has_active`, `sync_task_status`, `sync_task_prefix`, `normalize`, `recover_launched`, `list_launched`, `deadline_fail`
- CLI: `python3 engine/inbox.py <command> --flag value` (identical interface to Ruby)
- Lock: `fcntl.flock()` on `inbox.yaml.flock`
- Write: `tempfile.NamedTemporaryFile` + `os.rename`
- Header: preserve `# Delegation inbox\n# status: ...` comment
- Helpers to port: `load_yaml_document`, `load_items`, `write_items`, `with_inbox_lock`, `append_archive`, `process_alive?`, `strict_int`, `norm_priority`, `discussion_round_task?`
- Key flags: `--file`, `--id`, `--to`, `--task`, `--project`, `--priority`, `--created-at`, `--from`, `--now`, `--stamp-key`, `--key`, `--value`, `--by`, `--drop-status`, `--drop-prefix`, `--archive-file`, `--timeout-minutes`, `--action`, `--reason`, `--task-prefix`, `--retry-count`, `--max-retries`
- Existing tests to match: `test_engine_inbox.py`, `test_inbox_enqueue.py`, `test_inbox_recover.py`, `test_inbox_deadline.py`

### M2 — contract.py (claude-code)

- Port: `engine/contract.rb` (156 lines, 7 commands)
- Commands: `task_exists`, `task_project_path`, `task_owner`, `task_status`, `contract_id`, `task_deadline_minutes`, `latest_handoff_task`
- Read-only queries — no writes, no locking
- Key flags: `--file`, `--task`, `--dir`, `--to`
- Existing tests to match: `test_engine_contract.py`

### M3 — validate.py (codex-cli)

- Port: `engine/validate.rb` (123 lines)
- Single command: hygiene validation with JSON output
- Checks: file/dir existence, done task → handoff matching, done task → ledger matching, decision/failure store promotion
- Read-only, no locking
- Key flags: `--project`, `--strict`
- Existing tests to match: `test_engine_validate.py`, `test_contract_hygiene.py`

### M4 — discuss.py (claude-code)

- Port: `engine/discuss.rb` (307 lines, 2 commands)
- Commands: `status`, `approve`
- Lock: multi-file flock (handoff → contract → inbox) via `with_multi_lock`
- Writes: atomic writes to handoff, contract, inbox
- Helpers to port: `with_file_lock`, `with_multi_lock`, `load_yaml`, `atomic_write`, `find_pending_handoff`
- Key flags: `--handoff-dir`, `--contract-file`, `--inbox-file`, `--task`, `--project-dir`, `--by`, `--note`
- Existing tests to match: `test_discuss_approval.py`

### M5 — discussion.py (codex-cli)

- Port: `engine/discussion.rb` (461 lines, 12 commands)
- Commands: `start`, `submit_round`, `check_round`, `note_dispatch`, `check_consensus`, `advance`, `status`, `list`, `close`, `export`, `finalize`, `round_context`
- Lock: flock on `state.yaml`
- Helpers to port: `with_file_lock`, `load_yaml`, `atomic_write`, `generate_id`, `round_file`, `state_file`, `discussion_active!`, `dispatch_attempts`, `set_dispatch_attempts`, `validate_verdict!`, `load_submission`
- Key features: `schema_version: 1`, `VALID_VERDICTS` constant, `TERMINAL_STATUSES` constant, `--submission-file` for agent-written YAML input
- Key flags: `--discussions-dir`, `--discussion-dir`, `--topic`, `--participant` (multi), `--max-rounds`, `--task`, `--project`, `--created-by`, `--round`, `--agent`, `--verdict`, `--position`, `--points-file`, `--submission-file`, `--max-attempts`, `--outcome`, `--handoff-file`, `--markdown-report`

### M6 — task.py (claude-code)

- Port: `scripts/task.sh` inline Ruby heredocs (383 lines, 3 subcommands)
- Commands: `create`, `delete`, `status`
- Features: task dependency validation, owner-actor permission checks, dependency blocking logic, inbox sync on terminal status
- Imports `engine.contract` directly (no subprocess)
- Key flags: `--id`, `--title`, `--owner`, `--status`, `--dependency`, `--project`, `--actor`, `--reason`, `--summary`
- Existing tests to match: `test_task_failed_reason.py`

### M7 — contract_today.py (codex-cli)

- Port: `scripts/contract-today.sh` inline Ruby (158 lines)
- Table rendering, approval detection, delegate suggestion
- Imports `engine.contract` directly
- Key flags: `--project` (`-p`), `--agent`

### M8 — inbox_dispatch.py (claude-code)

- Port: `scripts/inbox-dispatch.sh` (447 lines)
- Imports `engine.inbox`, `engine.contract` directly
- Retains `subprocess.exec` for launching `claude`/`codex` CLIs
- Features: lock management, item parsing, worktree dirty-state detection (excludes `.superharness/`), launcher invocation, discussion round detection, reconciliation on non-interactive exit
- Key flags: `--project` (`-p`), `--to`, `--print-only`, `--non-interactive`, `--codex-bypass`, `--launcher-timeout`
- Existing tests to match: `test_inbox_dispatch.py`

### M9 — delegate.py (codex-cli)

- Port: `scripts/delegate.sh` (409 lines)
- Prompt generation via string templates
- Features: dual dispatch (claude-code + codex-cli), discussion round detection via regex, auto-directive for non-interactive mode, `run_command_capture_rc()`, `submit_staged_discussion_round()`
- CLI launching via `os.execvp`
- Key flags: `--to`, `--project` (`-p`), `--task` (`-t`), `--print-only`, `--non-interactive`, `--codex-bypass`
- Existing tests to match: `test_delegate.py`

### M10 — discuss_cli.py (claude-code)

- Port: `scripts/discuss.sh` (262 lines, 7 subcommands)
- Subcommands: `status`, `approve`, `start`, `rounds`, `consensus`, `list`, `repair`
- Features: clean worktree check (`project_has_dirty_worktree`), dirty worktree bypass (`--allow-dirty-worktree`, `SUPERHARNESS_ALLOW_DIRTY_DISCUSSION`), interactive confirmation, repair subcommand
- Imports `engine.discuss`, `engine.discussion`, `engine.inbox` directly
- Key flags: `--project` (`-p`), `--task`, `--by`, `--note`, `--topic`, `--max-rounds`, `--allow-dirty-worktree`, `--id`

### M11 — discussion_dispatch.py (codex-cli)

- Port: `scripts/discussion-dispatch.sh` (122 lines)
- Scans active discussions, advances rounds, enqueues items
- Features: `finalize_terminal_discussion()` generates handoff YAML + markdown transcript, `enqueue_round_item()` with `note_dispatch` integration, contract task status updates, ledger entries, `sync_task_prefix` for bulk inbox cleanup
- Imports `engine.discussion`, `engine.inbox`, `engine.contract` directly
- Key flags: `--project` (`-p`), `--id`
- Env: `SUPERHARNESS_DISCUSSION_MAX_ATTEMPTS` (default: 3)

---

## Swap Phases

### S1 — Swap Bash callers (after M1–M5 all green)

One commit per Bash file. Change `ruby engine/<name>.rb` to `python3 engine/<name>.py`:
- `scripts/inbox-dispatch.sh`
- `scripts/inbox-enqueue.sh`
- `scripts/inbox-recover-stale.sh`
- `scripts/inbox-normalize.sh`
- `scripts/inbox-deadline-check.sh`
- `scripts/discuss.sh`
- `scripts/discussion-dispatch.sh`
- `scripts/delegate.sh`
- `scripts/delegate-task.sh`
- `scripts/task.sh`
- `scripts/contract-today.sh`
- `scripts/check-contract-hygiene.sh`

### S2 — Update entrypoint + cli/ routing (after M6–M11 all green)

Update `superharness` (130 lines) and `cli/` shims to route to `.py` scripts:
- `cli/task.sh` → `cli/task.py` (or inline in entrypoint)
- `cli/contract-today.sh` → `cli/contract_today.py`
- `cli/discuss.sh` → `cli/discuss_cli.py`
- `cli/delegate.sh` → `cli/delegate.py`
- `cli/dispatch.sh` → `cli/dispatch.py`
- etc.

The 15 `cli/*.sh` shims (5 lines each, just `exec bash scripts/*.sh "$@"`) become `exec python3 scripts/*.py "$@"` — or can be eliminated entirely if the entrypoint routes directly.

### S3 — Cleanup

- Delete all `engine/*.rb` files
- Delete `scripts/inbox-yaml.rb`
- Remove `ruby` from `scripts/doctor.sh` (174 lines) dependency checks
- Add `python3 >= 3.11` check if not present
- Update `requirements.txt` with explicit `pyyaml` dependency
- Run full `pytest tests/` → green → commit

---

## Isolation Rules

1. **No module touches another module's files** — ever
2. **New Python files only** — no editing existing `.rb` or `.sh` until S1/S2
3. **Tests use `_py` suffix** — `test_engine_inbox_py.py` alongside existing `test_engine_inbox.py`
4. **Conformance tests** verify Ruby and Python produce identical output
5. **S1 swap is atomic per script** — one Bash file changed per commit

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| YAML output differs (key order, quoting) | Conformance tests in Step 3; use `sort_keys=False`, custom Dumper |
| File locking incompatibility during dual-run | `fcntl.flock()` and Ruby `File.flock()` both use POSIX `flock(2)` — interoperable |
| Watcher downtime during swap | Swap callers atomically per script, `launchctl unload/load` between cycles |
| `datetime` parsing edge cases | Use `datetime.fromisoformat()` (Python 3.11+ handles `Z` suffix) |
| Process kill check differences | `os.kill(pid, 0)` has same semantics as Ruby `Process.kill(0, pid)` |
| Inline Ruby heredocs in Bash scripts | `task.sh`, `discussion-dispatch.sh`, `discuss.sh` embed Ruby heredocs for contract/YAML manipulation. Python ports replicate as native Python |
| Discussion submission file format | `submit_round` accepts `--submission-file` (agent-written YAML). Python must parse identically to Ruby `Psych.safe_load` |
| Worker guardrails in inbox-watch.sh | `validate_worker_guardrails()` and `sync_worker_copy()` remain in Bash (inbox-watch.sh is not ported). Ensure Python engines called from watch loop produce identical exit codes |
| Existing test breakage | 29 unit + 6 integration tests call Ruby via Bash scripts. These keep working until S1 swap — no dual-run risk |

---

## Contract Tasks

```yaml
- id: migration-m0-yaml-helpers
  title: "TDD port: engine/yaml_helpers.rb → engine/yaml_helpers.py"
  owner: any
  status: todo

- id: migration-m1-inbox-py
  title: "TDD port: engine/inbox.rb → engine/inbox.py"
  owner: codex-cli
  status: todo

- id: migration-m2-contract-py
  title: "TDD port: engine/contract.rb → engine/contract.py"
  owner: claude-code
  status: todo

- id: migration-m3-validate-py
  title: "TDD port: engine/validate.rb → engine/validate.py"
  owner: codex-cli
  status: todo

- id: migration-m4-discuss-py
  title: "TDD port: engine/discuss.rb → engine/discuss.py"
  owner: claude-code
  status: todo

- id: migration-m5-discussion-py
  title: "TDD port: engine/discussion.rb → engine/discussion.py"
  owner: codex-cli
  status: todo

- id: migration-m6-task-py
  title: "TDD port: scripts/task.sh → scripts/task.py"
  owner: claude-code
  status: todo

- id: migration-m7-contract-today-py
  title: "TDD port: scripts/contract-today.sh → scripts/contract_today.py"
  owner: codex-cli
  status: todo

- id: migration-m8-inbox-dispatch-py
  title: "TDD port: scripts/inbox-dispatch.sh → scripts/inbox_dispatch.py"
  owner: claude-code
  status: todo

- id: migration-m9-delegate-py
  title: "TDD port: scripts/delegate.sh → scripts/delegate.py"
  owner: codex-cli
  status: todo

- id: migration-m10-discuss-cli-py
  title: "TDD port: scripts/discuss.sh → scripts/discuss_cli.py"
  owner: claude-code
  status: todo

- id: migration-m11-discussion-dispatch-py
  title: "TDD port: scripts/discussion-dispatch.sh → scripts/discussion_dispatch.py"
  owner: codex-cli
  status: todo

- id: migration-s1-swap-callers
  title: "Swap all Bash callers from ruby to python3"
  owner: any
  status: todo

- id: migration-s2-entrypoint
  title: "Update superharness entrypoint + cli/ routing to Python scripts"
  owner: any
  status: todo

- id: migration-s3-cleanup
  title: "Delete .rb files, remove ruby dependency"
  owner: any
  status: todo
```
