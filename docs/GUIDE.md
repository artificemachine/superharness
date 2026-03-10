# superharness User Guide

**Execution-first documentation for using superharness in your projects.**

---

## What is superharness?

superharness lets Claude Code and Codex CLI work on the same project without stepping on each other.
It gives you a shared contract, queue-based delegation, and handoff/ledger state so tasks survive across sessions.

**Core capabilities:**
- Multi-agent task coordination via shared contract
- Queue-based delegation with automatic dispatch
- Session handoff with state preservation
- Contract hygiene checks and protocol validation
- Background watcher for unattended execution

---

## Prerequisites

- `bash` (scripts are Bash-based)
- `ruby` (required by inbox YAML helpers and hygiene checks)
- `python3` (used by Claude session-start hook JSON escaping)
- `claude` CLI (for Claude delegation commands)
- `codex` CLI (for Codex delegation commands)
- macOS `launchd` is required only for background watcher install/ensure scripts

---

## Quick Start (3 Steps)

### 1. Install Claude hooks

```bash
bash adapters/claude-code/install.sh
```

This adds session-start and session-submit hooks to `~/.claude/settings.json`.

### 2. Initialize your project

```bash
cd /path/to/project
bash /path/to/superharness/superharness init "Project Name" "Tech/Stack" "active"
```

This creates `.superharness/` with:
- `contract.yaml` (task definitions, decisions, failures)
- `handoffs/` (session handoff state)
- `ledger.md` (append-only event log)
- `decisions.yaml` (cross-agent ADRs)
- `failures.yaml` (failure memory)
- `inbox.yaml` (dispatch queue)

### 3. Add a task and dispatch it

```bash
bash /path/to/superharness/superharness enqueue --project . --to codex-cli --task task-id --priority 1
bash /path/to/superharness/superharness dispatch --project . --to codex-cli --print-only
```

Use `--print-only` to preview the prompt without launching the CLI.

---

## Installation

### Install wrapper into PATH

```bash
bash /path/to/superharness/superharness install-wrapper
```

This symlinks the wrapper to `~/.local/bin/superharness` (add `~/.local/bin` to your PATH).

After installation, you can use:
```bash
superharness help
superharness contract today --project /path/to/project
```

---

## Core Commands

### Wrapper CLI

The thin dispatcher to all `cli/*.sh` commands:

```bash
bash /path/to/superharness/superharness help
```

After installing the wrapper:
```bash
superharness help
```

### Delegation

Launch a session for the next pending task:

```bash
bash /path/to/superharness/superharness delegate --to codex-cli --project /path/to/project
bash /path/to/superharness/superharness delegate --to claude-code --project /path/to/project
```

**Options:**
- `--task <TASK_ID>` — force a specific task (bypasses next-task logic)
- `--print-only` — generate prompt text without launching the CLI
- `--directive "extra instructions"` — append custom directive to prompt

**Shorthand by task id (auto-routes to task owner):**
```bash
bash /path/to/superharness/superharness delegate mcp-docs --project /path/to/project --print-only
```

**Compatibility shims (legacy):**
```bash
bash scripts/delegate-to-codex.sh --project /path/to/project
bash scripts/delegate-to-claude.sh --project /path/to/project
```

### Contract snapshot

```bash
bash /path/to/superharness/superharness contract today --project /path/to/project
```

Prints all tasks with id, status, owner, and suggests the next task to work on.

### Task management

```bash
# Guided interactive wizard
bash /path/to/superharness/superharness task

# Create task
bash /path/to/superharness/superharness task create --project /path/to/project --id task-id --title "Task title" --owner codex-cli

# Create task with dependency
bash /path/to/superharness/superharness task create --project /path/to/project --id test-task --title "Run tests" --owner codex-cli --dependency task-id

# Update task status
bash /path/to/superharness/superharness task status --project /path/to/project --id task-id --status in_progress --actor codex-cli

# Delete task
bash /path/to/superharness/superharness task delete --project /path/to/project --id task-id
```

### Inbox queue

**Enqueue a task:**
```bash
bash /path/to/superharness/superharness enqueue --project /path/to/project --to codex-cli --task task-id --priority 1
```

**Dispatch next pending item:**
```bash
bash /path/to/superharness/superharness dispatch --project /path/to/project --to codex-cli
```

Use `--print-only` to preview without launching.

**Start watcher (foreground):**
```bash
bash /path/to/superharness/superharness watch --project /path/to/project --to both
```

**Inbox status flow:**
1. `pending` → `launched` (dispatch claims item; retry count increments)
2. `launched` → `running` (agent begins work)
3. `running` → `done` or `failed` (agent completes or errors)

### Inbox maintenance

**Recover stale launched items:**
```bash
bash /path/to/superharness/superharness recover --project /path/to/project --timeout-minutes 20 --action stale
```

Items marked `launched` but not updated within timeout are marked `stale`.

**Normalize inbox (archive done/failed):**
```bash
bash /path/to/superharness/superharness normalize --project /path/to/project --archive
```

Archives `done` and `failed` items to `.superharness/inbox-archive.yaml`.

---

## Background Watcher (macOS launchd)

**Install background watcher:**
```bash
bash scripts/install-launchd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30 \
  --confirm-non-interactive yes \
  --confirm-skip-permissions yes
```

**Ensure watcher is running:**
```bash
bash scripts/ensure-launchd-inbox-watcher.sh --project /path/to/project
```

**Uninstall watcher:**
```bash
bash scripts/uninstall-launchd-inbox-watcher.sh --project /path/to/project
```

**Notes:**
- Avoid `~/Documents`, `~/Desktop`, and `~/Downloads` for watcher-managed projects on macOS; launchd can fail with `Operation not permitted` there.
- The watcher will not install unattended launch mode unless you explicitly confirm each required risk flag.
- Watcher logs are written to `~/Library/Logs/superharness/com.superharness.inbox.<project-name>-.out.log`.

**Watcher environment variables:**
- `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES` — required for unattended dispatch
- `SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES` — bypass permission prompts (danger zone)

---

## Protocol Hygiene

**Run hygiene checks:**
```bash
bash /path/to/superharness/superharness hygiene --project /path/to/project
```

**Strict mode (requires promotion alignment):**
```bash
bash /path/to/superharness/superharness hygiene --project /path/to/project --strict
```

**What hygiene checks validate:**
- Contract YAML structure and required fields
- Task status transitions (no invalid states)
- Handoff files match done tasks
- Ledger entries exist for completed work
- Decisions/failures promotion alignment (strict mode only)

### Failure-memory promotion workflow

1. Record task-local incidents in `.superharness/contract.yaml` under `failures`.
2. Promote reusable incidents to `.superharness/failures.yaml` under top-level `failures`.
3. Keep strict hygiene green by ensuring promoted failures are not left only in the contract.

---

## Doctor Checks

**Run environment validation:**
```bash
bash /path/to/superharness/superharness doctor --project /path/to/project
```

Checks for:
- Required executables (`bash`, `ruby`, `python3`, `claude`, `codex`)
- Protocol directory structure
- YAML syntax validity
- File permissions

---

## Monitor UI

**Launch browser-based monitor:**
```bash
bash /path/to/superharness/superharness monitor-ui --project /path/to/project
```

The monitor UI includes:
- Watcher state + inbox counters
- One-click queue actions (`dispatch preview`, `recover retry`, `normalize stale`)
- Optional `Open in Logdy` deep log view (only if `logdy` is installed)

**Security:**
- Monitor binds to loopback only (127.0.0.1)
- Mutating actions protected with per-session token
- Token is printed to terminal on startup

---

## CI and Local Guardrails

**Run shell entrypoint guard:**
```bash
bash scripts/check-shell-entrypoints.sh
```

**Install git pre-commit hook:**
```bash
bash scripts/install-git-hooks.sh
```

**Guard guarantees:**
- Explicit allowlist for executable shell entrypoints
- Shebang presence on all shell scripts
- Executable mode (`100755` for tracked files)
- `bash -n` syntax validity

---

## Repository Layout

```text
superharness/
├── superharness            # thin command dispatcher
├── protocol/              # protocol spec + templates
├── engine/                # ruby runtime helpers (yaml/queue/validation)
├── cli/                   # primary user-facing shell commands
├── adapters/              # Claude/Codex adapter assets
├── scripts/               # compatibility shims + launchd + guard scripts
├── docs/                  # architecture and rationale docs
├── tests/                 # unit/integration/e2e tests
├── init-project.sh
├── ROADMAP.md
└── CHANGELOG.md
```

Archived historical/reference material lives in `archive/reference/`.

---

## Project Runtime State

Per-project state is under `.superharness/`:

```text
.superharness/
├── contract.yaml          # tasks, decisions, failures
├── handoffs/              # session handoff state
│   └── <task-id>.yaml
├── ledger.md              # append-only event log
├── decisions.yaml         # cross-agent ADRs
├── failures.yaml          # failure memory
└── inbox.yaml             # dispatch queue
```

**Optional:**
- `inbox-archive.yaml` (archived done/failed items)

---

## Troubleshooting

### Watcher not dispatching

**Check watcher logs:**
```bash
tail -f ~/Library/Logs/superharness/com.superharness.inbox.<project-name>-.out.log
```

**Common issues:**
- `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES` not set in plist
- Project path in restricted directory (`~/Documents`, `~/Desktop`, `~/Downloads`)
- `codex` or `claude` CLI not in PATH

### Inbox items stuck in `launched`

**Recover stale items:**
```bash
bash /path/to/superharness/superharness recover --project /path/to/project --timeout-minutes 20 --action stale
```

### Hygiene failures

**Check which hygiene rules failed:**
```bash
bash /path/to/superharness/superharness hygiene --project /path/to/project
```

**Common failures:**
- Missing handoff for done task → create handoff YAML in `.superharness/handoffs/`
- Missing ledger entry → append one line to `.superharness/ledger.md`
- Contract decisions not promoted → move reusable decisions to `.superharness/decisions.yaml`

---

## Next Steps

- **Architecture:** [docs/ARCHITECTURE.md](ARCHITECTURE.md) — how superharness works internally
- **Security:** [SECURITY.md](../SECURITY.md) — operational safety notes
- **Roadmap:** [ROADMAP.md](../ROADMAP.md) — current maturity target and next milestones
- **Changelog:** [CHANGELOG.md](../CHANGELOG.md) — version history

---

**Current Version:** See [ROADMAP.md](../ROADMAP.md) for maturity target.
