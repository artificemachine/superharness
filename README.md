# superharness

**Multi-agent task coordination for Claude Code and Codex CLI**

superharness lets AI coding assistants work on the same project without stepping on each other. It provides a shared contract, queue-based delegation, and handoff/ledger state so tasks survive across sessions.

---

## Quick Links

📘 **[User Guide](docs/GUIDE.md)** — How to use superharness (installation, commands, troubleshooting)
🏗️ **[Architecture](docs/ARCHITECTURE.md)** — Why it exists, how it works, design philosophy
⚡ **[Quickstart](docs/QUICKSTART.md)** — Shortest path to first delegation
🔒 **[Security](SECURITY.md)** — Operational safety notes
🗺️ **[Roadmap](ROADMAP.md)** — Current maturity target and next milestones

---

## What You Get

- **`superharness init`** — Bootstrap protocol files (`.superharness/`)
- **`superharness delegate`** — Launch agent with contract context
- **`superharness enqueue|dispatch|watch`** — Queue-based task routing
- **`superharness hygiene`** — Protocol compliance checks
- **`superharness watch --foreground`** — Cross-platform continuous watcher
- **`superharness doctor`** — Prerequisite and setup health check
- **`superharness uninstall`** — Clean removal of system artifacts
- **Background watcher** — Unattended execution via macOS launchd or Linux systemd (opt-in)

---

## Quick Start

> **Requires:** `bash`, `ruby`, `python3`. See [Prerequisites](#prerequisites) for install commands.

### 0. Install the CLI
```bash
bash scripts/install-wrapper.sh
# Creates a symlink at ~/.local/bin/superharness
# If ~/.local/bin is not in PATH: export PATH="$HOME/.local/bin:$PATH"
```

### 1. Initialize your project
```bash
cd /path/to/project
superharness init "Project Name" "Tech/Stack" "active"
# Creates .superharness/, CLAUDE.md, and AGENTS.md in your project root
```

### 2. Verify setup
```bash
superharness doctor --project .
```

### 3. Create a task and dispatch it
```bash
superharness task create --project . --id my-task --title "First task" --owner codex-cli
superharness enqueue --project . --to codex-cli --task my-task --priority 1
superharness dispatch --project . --to codex-cli --print-only
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

### Run Tests

```bash
pip install -r requirements.txt
pytest tests/ -q
```

| **Smoke**       |
| --------------- |
| **Unit**        |
| **Integration** |
| **E2E**         |

### Readiness Audits

Use this command for a generic cross-repo quality audit:

```bash
$production-ready
```

Use this command for superharness-specific release quality policy:

```bash
$superharness-production-ready
```

Rule of thumb:
- Use `$production-ready` when working in any repository.
- Use `$superharness-production-ready` when working in this repository and you want local mandatory checks (contract protocol, regression guard, watcher/doctor posture).

---

## Prerequisites

- `bash` (scripts are Bash-based)
- `ruby` (required by inbox YAML helpers and hygiene checks) — see `.ruby-version`
- `python3` + `pytest` (tests and hook JSON escaping) — `pip install -r requirements.txt`
- `claude` CLI (for Claude delegation commands): `npm install -g @anthropic-ai/claude-code`
- `codex` CLI (for Codex delegation commands): `npm install -g @openai/codex`
- macOS `launchd` or Linux `systemd` for background watcher (see `scripts/superharness-watcher@.service`); `--foreground` mode works everywhere

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

TODO (repo governance):
- Enforce branch protection required checks server-side on `main` once plan supports private-repo protections:
  - `Tests / QA Gate`
  - `Security / ShipGuard Scan`
  - `Shell Guards / Shebang + Execute Bit Guard`
  - `Contract Hygiene / Protocol Hygiene Check`

---

## Current Version

Current execution maturity target: **v0.7** (reliability and adoption milestone)

See [ROADMAP.md](ROADMAP.md) for details, [RELEASES.md](RELEASES.md) for release notes, and [CHANGELOG.md](CHANGELOG.md) for the full iteration log.
