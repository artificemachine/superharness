# superharness

**Multi-agent task coordination for Claude Code and Codex CLI**

superharness lets AI coding assistants work on the same project without stepping on each other. It provides a shared contract, queue-based delegation, and handoff/ledger state so tasks survive across sessions.

> **AI agent installing this?** Read [`docs/INSTALL-AGENT.md`](docs/INSTALL-AGENT.md) — it tells you exactly what to detect, what to ask the user (just two questions), and how to set everything up without human terminal interaction.

---

## Using superharness

### Via Claude Code or Codex CLI (recommended)

**Step 1 — Install superharness once (terminal):**
```bash
git clone https://github.com/celstnblacc/superharness.git
cd superharness
bash scripts/install-wrapper.sh
# export PATH="$HOME/.local/bin:$PATH"  # add to ~/.zshrc or ~/.bashrc if needed
```

**Step 2 — Go to your project and open Claude Code or Codex CLI.**

**Step 3 — Type these phrases directly to the agent:**
```
shux init              # bootstrap .superharness/ for this project
shux doctor            # check prerequisites and protocol health
shux contract          # show all tasks with status and next-task suggestion
shux continue          # resume active contract automatically
shux delegate <id>     # create task + enqueue in one step
shux close <id>        # mark done, append ledger, write handoff
shux status            # dashboard: tasks, watcher, profile
shux recall <keywords> # search past handoffs and ledger
shux uninstall         # remove watcher and system artifacts for this project
shux hygiene           # validate protocol compliance (contract, handoffs, ledger)
shux monitor           # open browser dashboard
shux watch             # start continuous watcher in foreground
shux update            # pull latest superharness + refresh CLAUDE.md, AGENTS.md, templates
```

**That's it.** Steps 1 and 2 are one-time. From then on, `shux contract` starts every session.

---

### Via Terminal (alternative)

For scripting, CI, or users who prefer direct shell access.

> **Requires:** `bash`, `ruby`, `python3`. See [Prerequisites](#prerequisites).

```bash
# Try first — no install needed
bash scripts/demo.sh

# Install CLI
bash scripts/install-wrapper.sh && superharness version

# Initialize project
cd /path/to/project
superharness init --interactive   # or: superharness init "Name" "Stack" "active"

# Verify
superharness doctor --project .

# Contract snapshot
superharness contract today --project .

# Delegate to agent
superharness delegate --to codex-cli --project .

# Queue management
superharness enqueue --project . --to codex-cli --task my-task --priority 1
superharness dispatch --project . --to codex-cli

# Protocol hygiene + browser monitor
superharness hygiene --project .
superharness monitor-ui --project .
```

**Run tests:**
```bash
uv sync --dev
pytest tests/ -q
```

**Full terminal reference:** [docs/GUIDE.md](docs/GUIDE.md)

---

## Quick Links

📘 **[User Guide](docs/GUIDE.md)** — Commands, background watcher, troubleshooting
🏗️ **[Architecture](docs/ARCHITECTURE.md)** — Why it exists, how it works, design decisions
🔒 **[Security](SECURITY.md)** — Threat model and operational safety notes

---

## What You Get

- **`shux` shortcuts** — Control superharness from inside Claude Code or Codex CLI
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
| Agent shortcuts (`shux`) | + `claude` or `codex` CLI |
| Background auto-dispatch | + launchd (macOS); systemd unit provided but untested |
| Browser dashboard | + `python3 -m http.server` (built-in) |

**You can start with just the core** and add agent CLIs and background services later. `--print-only` mode lets you preview every dispatch without launching anything.

---

## Platform Support

**Developed and tested on macOS.** The core protocol (contracts, handoffs, ledger, engine commands, `shux` shortcuts) uses portable bash/ruby/python and should work on Linux. However:

- **Background watcher installer** is macOS-only (`launchd`). A systemd unit file is provided (`scripts/superharness-watcher@.service`) but has no automated installer yet. `--foreground` mode works everywhere.
- **`stat` calls** include both macOS and Linux fallbacks.
- Linux contributions welcome — see [CONTRIBUTING.md](docs/CONTRIBUTING.md).

## Prerequisites

- `bash` 4+ (scripts are Bash-based)
- `ruby` (required by inbox YAML helpers and hygiene checks) — see `.ruby-version`
- `python3` + `pytest` (tests and hook JSON escaping) — `uv sync --dev` (or `pip install pytest pytest-cov pyyaml`)
- `claude` CLI (for Claude delegation commands): `npm install -g @anthropic-ai/claude-code`
- `codex` CLI (for Codex delegation commands): `npm install -g @openai/codex`
- macOS `launchd` for background watcher (see Platform Support above); `--foreground` mode works everywhere

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

Current version: **v0.8.0**

See [CHANGELOG.md](CHANGELOG.md) for the full iteration log.
