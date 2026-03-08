# superharness

superharness is a cross-agent execution harness for Claude Code and Codex CLI.

It provides:
- project bootstrap (`init-project.sh`)
- Claude hooks (session context + guardrails)
- contract/handoff/ledger protocol files
- delegation inbox queue + dispatch/watch automation
- shell entrypoint integrity guard in CI and pre-commit

Architecture and philosophy are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Prerequisites

- `bash` (scripts are Bash-based)
- `ruby` (required by inbox YAML helpers and hygiene checks)
- `python3` (used by Claude session-start hook JSON escaping)
- `claude` CLI (for Claude delegation commands)
- `codex` CLI (for Codex delegation commands)
- macOS `launchd` is required only for background watcher install/ensure scripts

## Quick Start

1. Install Claude plugin hooks:
```bash
bash adapters/claude-code/install.sh
```

2. Initialize a project:
```bash
cd /path/to/project
bash /path/to/superharness/init-project.sh "Project Name" "Tech/Stack" "active"
```

3. Review generated files:
- `CLAUDE.md`
- `AGENTS.md`
- `.superharness/contract.yaml`

4. Add first tasks in `.superharness/contract.yaml` with absolute `project_path` values.

## Core Commands

### Delegation launchers
```bash
bash scripts/delegate-to-codex.sh --project /path/to/project
bash scripts/delegate-to-claude.sh --project /path/to/project
```

Use `--task <TASK_ID>` to force a specific task.
Use `--print-only` to generate prompt text without launching the CLI.

### Inbox queue
```bash
bash scripts/inbox-enqueue.sh --project /path/to/project --to codex-cli --task task-id --priority 1
bash scripts/inbox-dispatch.sh --project /path/to/project
bash scripts/inbox-watch.sh --project /path/to/project --to both
```

Status flow:
- `pending` -> `launched` (dispatch claims item; retry count increments)
- `launched` -> `running` (agent begins work)
- then `done|failed` via lifecycle updates

### Inbox maintenance
```bash
bash scripts/inbox-normalize.sh --project /path/to/project --archive
```

### macOS background watcher
```bash
bash scripts/install-launchd-inbox-watcher.sh --project /path/to/project --interval 30
bash scripts/ensure-launchd-inbox-watcher.sh --project /path/to/project
bash scripts/uninstall-launchd-inbox-watcher.sh --project /path/to/project
```

## Protocol Hygiene

Check project protocol quality:
```bash
bash scripts/check-contract-hygiene.sh --project /path/to/project
```

Strict mode also requires promotion alignment for contract decisions/failures:
```bash
bash scripts/check-contract-hygiene.sh --project /path/to/project --strict
```

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

```text
superharness/
├── adapters/              # Claude/Codex adapter assets
├── scripts/               # dispatch, delegation, launchd, guard scripts
├── identity/              # base identity content
├── agents/                # protocol + review lenses
├── knowledge/             # decision/failure/vault references
├── methodology/           # routing and review method docs
├── state/                 # state protocol and templates
├── docs/                  # architecture and rationale docs
├── tests/                 # unit/integration/e2e tests
├── init-project.sh
├── ROADMAP.md
└── CHANGELOG.md
```

## Current Version

Current execution maturity target is tracked in [ROADMAP.md](ROADMAP.md).
