# superharness

**Multi-agent task coordination for Claude Code and Codex CLI**

superharness lets AI coding assistants work on the same project without stepping on each other. It provides a shared contract, queue-based delegation, and handoff/ledger state so tasks survive across sessions.

> **AI agent installing this?** Read [`docs/INSTALL-AGENT.md`](docs/INSTALL-AGENT.md) — it tells you exactly what to detect, what to ask the user (just two questions), and how to set everything up without human terminal interaction.

---

## Quick Links

📘 **[User Guide](docs/GUIDE.md)** — How to use superharness (installation, commands, troubleshooting)
🏗️ **[Architecture](docs/ARCHITECTURE.md)** — Why it exists, how it works, design philosophy
⚡ **[Quickstart](docs/QUICKSTART.md)** — Shortest path to first delegation
👥 **[Teams](docs/TEAMS.md)** — Multi-person setups, shared state, CI integration
🔒 **[Security](SECURITY.md)** — Operational safety notes
🗺️ **[Roadmap](docs/ROADMAP.md)** — Current maturity target and next milestones

---

## What You Get

- **`superharness demo`** — Zero-config walkthrough: see the full lifecycle in 30 seconds, no agent CLI needed
- **`superharness init`** — Bootstrap protocol files (`.superharness/`)
- **`superharness delegate`** — Launch agent with contract context
- **`superharness enqueue|dispatch|watch`** — Queue-based task routing
- **`superharness hygiene`** — Protocol compliance checks
- **`superharness watch --foreground`** — Cross-platform continuous watcher
- **`superharness monitor-ui`** — Browser dashboard: inbox, tasks, watcher state, plan approvals
- **`superharness doctor`** — Prerequisite and setup health check
- **`superharness uninstall`** — Clean removal of system artifacts
- **Background watcher** — Unattended execution via macOS launchd or Linux systemd (opt-in)

---

## Is this for me?

superharness is for you if **any** of these are true:
- You use Claude Code or Codex CLI and find yourself re-explaining project context at the start of every session
- You want to hand off a task to one agent while you work with another
- You need an append-only audit trail of what each agent did and decided
- You run agents unattended in the background (e.g. via launchd/systemd)

You probably **don't need** superharness if you only ever run a single agent interactively and don't switch between sessions.

### What you need to use it

| Feature | Requirements |
|---------|-------------|
| Core protocol (contracts, handoffs, ledger) | `bash`, `ruby`, `python3` |
| Delegation + dispatch preview | + any text editor |
| Live delegation to an agent | + `claude` or `codex` CLI |
| Background auto-dispatch | + launchd (macOS) or systemd (Linux) |
| Browser dashboard | + `python3 -m http.server` (built-in) |

**You can start with just the core** and add agent CLIs and background services later. `--print-only` mode lets you preview every dispatch without launching anything.

---

## Quick Start

> **Requires:** `bash`, `ruby`, `python3`. See [Prerequisites](#prerequisites) for install commands.

### Try it first (no install needed)
```bash
bash scripts/demo.sh
# Runs a full task lifecycle in a temp dir — nothing installed, no agent CLI required
```

### 0. Install the CLI
```bash
bash scripts/install-wrapper.sh
# Creates a symlink at ~/.local/bin/superharness
# If ~/.local/bin is not in PATH: export PATH="$HOME/.local/bin:$PATH"

# Verify it worked:
superharness version
```

### 1. Initialize your project
```bash
cd /path/to/project
superharness init "Project Name" "Tech/Stack" "active"
# Creates .superharness/, CLAUDE.md, and AGENTS.md in your project root

# Decide: commit state files or ignore them
echo '.superharness/' >> .gitignore   # option A: ignore (recommended for personal projects)
# — OR — git add .superharness/       # option B: commit (recommended for team projects)
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

| Layer | Description |
| ------------- | ------------------------------------------ |
| **Smoke** | Entrypoint `--help` and import checks |
| **Unit** | Isolated function/script tests |
| **Integration** | Cross-script workflow tests |
| **E2E** | Full contract lifecycle tests |

### Readiness Audits

Use this command for a generic cross-repo quality audit:

In Claude Code, run:
```
/production-ready
```

Use this command for superharness-specific release quality policy:

```
/superharness-production-ready
```

Rule of thumb:
- Use `/production-ready` when working in any repository.
- Use `/superharness-production-ready` when working in this repository and you want local mandatory checks (contract protocol, regression guard, watcher/doctor posture).

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

See [ROADMAP.md](docs/ROADMAP.md) for details, [RELEASES.md](docs/RELEASES.md) for release notes, and [CHANGELOG.md](CHANGELOG.md) for the full iteration log.
