# superharness

superharness lets Claude Code and Codex CLI work on the same project without stepping on each other.
It gives you a shared contract, queue-based delegation, and handoff/ledger state so tasks survive across sessions.

What you get:
- `superharness init` to bootstrap protocol files
- `superharness delegate|enqueue|dispatch|watch` for cross-agent routing
- stale launched-item recovery + inbox normalization
- contract hygiene checks and shell entrypoint guardrails

Architecture and philosophy are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Fast path setup is in [docs/QUICKSTART.md](docs/QUICKSTART.md).
Operational safety notes are in [SECURITY.md](SECURITY.md).

## Prerequisites

- `bash` (scripts are Bash-based)
- `ruby` (required by inbox YAML helpers and hygiene checks)
- `python3` (used by Claude session-start hook JSON escaping)
- `claude` CLI (for Claude delegation commands)
- `codex` CLI (for Codex delegation commands)
- macOS `launchd` is required only for background watcher install/ensure scripts

## 3-Step Start

1. Install Claude hooks:
```bash
bash adapters/claude-code/install.sh
```

2. Initialize your project:
```bash
cd /path/to/project
bash /path/to/superharness/superharness init "Project Name" "Tech/Stack" "active"
```

3. Add a task and dispatch it:
```bash
bash /path/to/superharness/superharness enqueue --project . --to codex-cli --task task-id --priority 1
bash /path/to/superharness/superharness dispatch --project . --to codex-cli --print-only
```

## Core Commands

Use the wrapper CLI (thin dispatcher to `cli/*.sh`):
```bash
bash /path/to/superharness/superharness help
```

Install wrapper into PATH:
```bash
bash /path/to/superharness/superharness install-wrapper
```

### Delegation launchers
```bash
bash /path/to/superharness/superharness delegate --to codex-cli --project /path/to/project
bash /path/to/superharness/superharness delegate --to claude-code --project /path/to/project
```

Use `--task <TASK_ID>` to force a specific task.
Use `--print-only` to generate prompt text without launching the CLI.
Shorthand by task id (auto owner routing):
```bash
bash /path/to/superharness/superharness delegate mcp-docs --project /path/to/project --print-only
```

### Contract snapshot
```bash
bash /path/to/superharness/superharness contract today --project /path/to/project
```

### Task helper (guided)
```bash
bash /path/to/superharness/superharness task
bash /path/to/superharness/superharness task create --project /path/to/project --id task-id --title "Task title" --owner codex-cli
bash /path/to/superharness/superharness task create --project /path/to/project --id test-task --title "Run tests" --owner codex-cli --dependency task-id
bash /path/to/superharness/superharness task status --project /path/to/project --id task-id --status in_progress --actor codex-cli
bash /path/to/superharness/superharness task delete --project /path/to/project --id task-id
```

Compatibility shims remain available:
```bash
bash scripts/delegate-to-codex.sh --project /path/to/project
bash scripts/delegate-to-claude.sh --project /path/to/project
```

### Inbox queue
```bash
bash /path/to/superharness/superharness enqueue --project /path/to/project --to codex-cli --task task-id --priority 1
bash /path/to/superharness/superharness dispatch --project /path/to/project
bash /path/to/superharness/superharness watch --project /path/to/project --to both
```

Status flow:
- `pending` -> `launched` (dispatch claims item; retry count increments)
- `launched` -> `running` (agent begins work)
- then `done|failed` via lifecycle updates

### Inbox maintenance
```bash
bash /path/to/superharness/superharness recover --project /path/to/project --timeout-minutes 20 --action stale
bash /path/to/superharness/superharness normalize --project /path/to/project --archive
```

### macOS background watcher
```bash
bash scripts/install-launchd-inbox-watcher.sh --project /path/to/project --interval 30 --confirm-non-interactive yes --confirm-skip-permissions yes
bash scripts/ensure-launchd-inbox-watcher.sh --project /path/to/project
bash scripts/uninstall-launchd-inbox-watcher.sh --project /path/to/project
```
Note: avoid `~/Documents`, `~/Desktop`, and `~/Downloads` for watcher-managed projects on macOS; launchd can fail with `Operation not permitted` there.
The watcher will not install unattended launch mode unless you explicitly confirm each required risk flag.

## Protocol Hygiene

Check project protocol quality:
```bash
bash /path/to/superharness/superharness hygiene --project /path/to/project
```

Strict mode also requires promotion alignment for contract decisions/failures:
```bash
bash /path/to/superharness/superharness hygiene --project /path/to/project --strict
```

### Doctor checks
```bash
bash /path/to/superharness/superharness doctor --project /path/to/project
```

### Browser monitor UI
```bash
bash /path/to/superharness/superharness monitor-ui --project /path/to/project
```
The monitor UI includes:
- watcher state + inbox counters
- one-click queue actions (`dispatch preview`, `recover retry`, `normalize stale`)
- optional `Open in Logdy` deep log view (only if `logdy` is installed)
The monitor binds to loopback only and protects mutating actions with a per-session token.

## CI And Local Guardrails

Run shell entrypoint guard:
```bash
bash scripts/check-shell-entrypoints.sh
```

Install git pre-commit hook:
```bash
bash scripts/install-git-hooks.sh
```

Guard guarantees:
- explicit allowlist for executable shell entrypoints
- shebang presence
- executable mode (`100755` for tracked files)
- `bash -n` syntax validity

## Repository Layout

Runtime directories:
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

## Current Version

Current execution maturity target is tracked in [ROADMAP.md](ROADMAP.md).
