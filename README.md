# superharness

**Multi-agent task coordination for Claude Code and Codex CLI**

superharness lets AI coding assistants work on the same project without stepping on each other. It provides a shared contract, queue-based delegation, and handoff/ledger state so tasks survive across sessions.

---

## Quick Links

📘 **[User Guide](docs/GUIDE.md)** — How to use superharness (installation, commands, troubleshooting)
🏗️ **[Architecture](docs/ARCHITECTURE.md)** — Why it exists, how it works, design philosophy
⚡ **[Quickstart](docs/QUICKSTART.md)** — Shortest path to first delegation (3 steps)
🔒 **[Security](SECURITY.md)** — Operational safety notes
🗺️ **[Roadmap](ROADMAP.md)** — Current maturity target and next milestones

---

## What You Get

- **`superharness init`** — Bootstrap protocol files (`.superharness/`)
- **`superharness delegate`** — Launch agent with contract context
- **`superharness enqueue|dispatch|watch`** — Queue-based task routing
- **`superharness hygiene`** — Protocol compliance checks
- **Background watcher** — Unattended execution via macOS launchd

---

## 3-Step Start

### 1. Install Claude hooks
```bash
bash adapters/claude-code/install.sh
```

### 2. Initialize your project
```bash
cd /path/to/project
bash /path/to/superharness/superharness init "Project Name" "Tech/Stack" "active"
```

### 3. Enqueue and dispatch a task
```bash
bash /path/to/superharness/superharness enqueue --project . --to codex-cli --task task-id --priority 1
bash /path/to/superharness/superharness dispatch --project . --to codex-cli --print-only
```

**Full setup guide:** [docs/QUICKSTART.md](docs/QUICKSTART.md)

---

## Core Commands

```bash
# Contract snapshot
superharness contract today --project /path/to/project

# Delegate to agent
superharness delegate --to codex-cli --project /path/to/project

# Queue management
superharness enqueue --project . --to codex-cli --task task-id --priority 1
superharness dispatch --project . --to codex-cli

# Protocol hygiene
superharness hygiene --project /path/to/project

# Browser monitor
superharness monitor-ui --project /path/to/project
```

**Full command reference:** [docs/GUIDE.md](docs/GUIDE.md)

---

## Prerequisites

- `bash` (scripts are Bash-based)
- `ruby` (required by inbox YAML helpers and hygiene checks)
- `python3` (used by Claude session-start hook JSON escaping)
- `claude` CLI (for Claude delegation commands)
- `codex` CLI (for Codex delegation commands)
- macOS `launchd` (only for background watcher install/ensure scripts)

---

## Project Runtime State

Per-project state lives in `.superharness/`:

```text
.superharness/
├── contract.yaml          # tasks, decisions, failures
├── handoffs/              # session handoff state
├── ledger.md              # append-only event log
├── decisions.yaml         # cross-agent ADRs
├── failures.yaml          # failure memory
└── inbox.yaml             # dispatch queue
```

**Architecture details:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## Repository Layout

```text
superharness/
├── superharness            # thin command dispatcher
├── protocol/              # protocol spec + templates
├── engine/                # ruby runtime helpers
├── cli/                   # primary shell commands
├── adapters/              # Claude/Codex adapter assets
├── scripts/               # launchd + guard scripts
├── docs/                  # architecture and user guide
├── tests/                 # unit/integration/e2e tests
└── CHANGELOG.md
```

---

## Security Note

The background watcher enables **unattended execution** (agents run without human supervision). This is powerful but requires explicit confirmation:

```bash
bash scripts/install-launchd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30 \
  --confirm-non-interactive yes \
  --confirm-skip-permissions yes
```

**Read the full threat model:** [SECURITY.md](SECURITY.md)

---

## Current Version

Current execution maturity target: **v0.7** (reliability and adoption milestone)

See [ROADMAP.md](ROADMAP.md) for details and [CHANGELOG.md](CHANGELOG.md) for version history.
