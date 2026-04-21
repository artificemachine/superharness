# superharness

**Multi-agent task coordination for Claude Code and Codex CLI**

superharness lets AI coding assistants work on the same project without stepping on each other. It provides a shared contract, queue-based delegation, and handoff/ledger state so tasks survive across sessions.

> **AI agent installing this?** Read [`docs/INSTALL-AGENT.md`](docs/INSTALL-AGENT.md) — it tells you exactly what to detect, what to ask the user (just two questions), and how to set everything up without human terminal interaction.

---

## Using superharness

### Via Claude Code or Codex CLI (recommended)

**Step 1 — Install superharness once (terminal):**
```bash
pipx install superharness
```

<details>
<summary>Alternative: install from source</summary>

```bash
curl -fsSL https://raw.githubusercontent.com/celstnblacc/superharness/main/scripts/install-remote.sh | bash
# export PATH="$HOME/.local/bin:$PATH"  # add to ~/.zshrc or ~/.bashrc if needed
```

Or clone manually:
```bash
git clone https://github.com/celstnblacc/superharness.git ~/.local/share/superharness
bash ~/.local/share/superharness/scripts/install-wrapper.sh
```
</details>

**Step 2 — Go to your project and open Claude Code or Codex CLI.**

**Step 3 — Type these phrases directly to the agent:**
```
shux explain           # what is superharness? (10-second answer — aliases: shux why, shux wtf)
shux onboard           # guided 7-step setup wizard (non-interactive: --non-interactive --git-mode team|solo)
shux init              # bootstrap .superharness/ for this project
shux doctor            # check prerequisites and protocol health
shux contract          # show all tasks with status and next-task suggestion
shux continue          # resume active contract automatically
shux delegate <id>     # create task + enqueue in one step (task must be plan_approved or later)
shux test-type <id>    # set mandatory test types for a task
shux verify <id>       # record verification result (pass/fail)
shux close <id>        # mark done (task must be report_ready or review_passed); use --cancel-remaining --cancel-reason "..." to bulk-cancel open subtasks and close atomically; --force bypasses all gates
shux subtask-cancel    # cancel a single subtask with a mandatory reason (--task <id> --sub <sub-id> --reason "...")
shux task create       # create a task with --blocked-by, --tdd-red/green/refactor, --criteria flags
shux task status       # update task lifecycle status (todo → plan_proposed → plan_approved → in_progress → report_ready → done)
shux status            # dashboard: tasks, watcher, profile
shux recall <keywords> # search past handoffs and ledger
shux uninstall         # remove watcher and system artifacts for this project
shux hygiene           # validate protocol compliance (contract, handoffs, ledger)
shux hygiene --repair  # auto-fix missing handoffs, ledger entries, and stuck statuses
shux dashboard         # open browser dashboard
shux watch             # start continuous watcher in foreground
shux update            # pull latest superharness + refresh templates, hooks, and watcher
shux discuss           # start or manage a cross-agent discussion (topic, owners, optional ID)
shux agent-pulse       # write/read agent liveness signal (heartbeat for running tasks)
shux auto-dispatch     # scan todo tasks, classify via model router, and enqueue to best agent
shux schedule          # cron-like scheduled dispatch: add/list/remove/run
shux install-hooks     # merge adapter hooks into ~/.claude/settings.json (portable, run once per machine)
shux init --skip-hooks # init without modifying ~/.claude/settings.json (for CI or conservative setups)
shux benchmark         # show dispatch cost/duration leaderboard (--top N, --agents, --models)
shux config get <key>  # read a profile.yaml setting (e.g. budget.daily_limit, default_model)
shux config set <key> <val>  # write a profile.yaml setting (e.g. budget.daily_limit 5.00, budget.strict true)
shux diff <id>         # preview agent changes for a task before closing (--stat, --base)
shux daemon start      # start background watcher daemon (portable, no launchd/systemd needed)
shux daemon stop       # stop the daemon
shux daemon status     # show daemon running state and PID
shux pack export       # bundle .superharness/ into a portable .tar.gz for handoff
shux pack import       # restore a pack into a new project
shux inbox-gc          # reconcile stale inbox items against contract
shux worktree-gc       # clean orphaned dispatch worktrees
shux recap             # what happened in the last N hours (timeline view)
shux notify-desktop    # send a native desktop notification
shux adapter-payload --json  # emit project state as stable JSON payload (schema v1.0) for Morpheme/adapters
shux help              # show all shux shortcuts in the terminal
```

**Dashboard features** (`shux dashboard`):
- Activity feed — live timeline of dispatch, gc, and inbox events
- Git context — branch, dirty file count, last commit in header
- Task dependency graph — press `g` to toggle
- Dispatch preview — model, effort, cost, timeout in enqueue modal
- Keyboard shortcuts — `r` refresh, `g` graph, `l` list, `b` board, `?` help

**That's it.** Steps 1 and 2 are one-time. From then on, `shux contract` starts every session.

---

### Intelligence layer (v1.7.0)

Dispatch is now smarter. These features activate automatically — no extra setup needed.

| Feature | What it does |
|---------|-------------|
| **Pre-flight analysis** | Validates task spec, TDD block, dependencies, and git state before dispatch. Blocks on unresolved deps, warns on missing criteria. |
| **Complexity estimator** | Scores acceptance criteria + TDD scope and suggests single/fanout/swarm mode. |
| **Failure pattern matching** | 15 built-in classifiers (ImportError, timeout, git conflict, etc.) analyze errors and inject fix hints into the next dispatch. |
| **Skill extraction** | When a task completes, extracts category, techniques, and diff stats into `skills.yaml`. Future dispatches for similar tasks get technique hints. |
| **Benchmark leaderboard** | Tracks cost, duration, and outcome per dispatch in `benchmark.jsonl`. View with `shux benchmark`. |
| **Parallel fan-out** | Run N agents concurrently on isolated git worktrees. Use `fanout_dispatch()` from the SDK. |
| **Swarm mode** | N workers solve the same task, then an Opus reviewer picks the best solution. Optional auto-merge. |

---

### Via Terminal (alternative)

For scripting, CI, or users who prefer direct shell access.

> **Requires:** `bash`, `python3`. See [Prerequisites](#prerequisites).

```bash
# Try first — no install needed
PYTHONPATH=src python3 -m superharness demo

# Install CLI
pipx install superharness && superharness --version

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

# Protocol hygiene + browser dashboard
superharness hygiene --project .
superharness dashboard-ui --project .
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
- **`superharness init`** — Bootstrap protocol files (`.superharness/`); auto-installs Claude Code hooks and background watcher (macOS)
- **`superharness task`** — Create and update tasks: `--blocked-by <id>` dependency tracking, `--tdd-red/green/refactor` TDD block, `--criteria` acceptance criteria; `task status` enforces the full lifecycle (todo → plan_proposed → plan_approved → in_progress → report_ready → done)
- **`superharness delegate`** — Launch agent with contract context (requires task status ≥ `plan_approved`; auto model routing)
- **`superharness verify`** — Record verification result before closing a task
- **`superharness close`** — Close a verified task (requires `report_ready` or `review_passed`; use `--force` to bypass lifecycle gate)
- **`superharness enqueue|dispatch|watch`** — Queue-based task routing
- **`superharness hygiene`** — Protocol compliance checks
- **`superharness watch --foreground`** — Cross-platform continuous watcher
- **`superharness dashboard-ui`** — Browser dashboard: inbox, tasks, watcher state, enqueue with TDD instructions
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
| Core protocol (contracts, handoffs, ledger) | `bash`, `python3` |
| Agent shortcuts (`shux`) | + `claude` or `codex` CLI |
| Background auto-dispatch | + launchd (macOS) or systemd (Linux) |
| Browser dashboard | + `python3 -m http.server` (built-in) |

**You can start with just the core** and add agent CLIs and background services later. `--print-only` mode lets you preview every dispatch without launching anything.

---

## Platform Support

**Cross-platform: macOS, Linux, Windows.** All user-facing commands are Python and work everywhere `python3` is available. CI runs on all three platforms.

- **Background watcher** has automated service installers for macOS (`launchd`), Linux (`systemd`), and Windows (Task Scheduler via `schtasks.exe`). `superharness watch --foreground` works everywhere as an alternative.

## Prerequisites

- `python3` 3.11+ + `pyyaml` — `uv sync --dev` (or `pip install pyyaml click ruamel.yaml`)
- `bash` — only needed for macOS/Linux watcher service install scripts; not required on Windows or for any core commands
- `claude` CLI (for Claude delegation commands): `npm install -g @anthropic-ai/claude-code`
- `codex` CLI (for Codex delegation commands): `npm install -g @openai/codex`
- macOS `launchd` or Linux `systemd` for background watcher (see Platform Support); `--foreground` mode works everywhere

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
├── superharness            # thin Bash shim → delegates to Python
├── src/superharness/       # Python CLI + engine + command modules
├── protocol/              # protocol spec + templates
├── adapters/              # Claude/Codex adapter assets
├── scripts/               # launchd installer + CI guard scripts
├── docs/                  # architecture and user guide
├── tests/                 # unit/integration/e2e tests
└── CHANGELOG.md
```

---

## Security Note

The background watcher enables **unattended execution** (agents run without human supervision). This is powerful but requires explicit confirmation:

**macOS (launchd):**
```bash
bash scripts/install-launchd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30 \
  --confirm-non-interactive yes \
  --confirm-skip-permissions yes
```

**Linux (systemd):**
```bash
CONFIRM_NON_INTERACTIVE=yes bash scripts/install-systemd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30
```

**Read the full threat model:** [SECURITY.md](SECURITY.md)

---

## Current Version

Current version: **v1.29.0**

See [CHANGELOG.md](CHANGELOG.md) for the full iteration log.
