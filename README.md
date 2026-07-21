# superharness

[![CI](https://github.com/artificemachine/superharness/actions/workflows/tests.yml/badge.svg)](https://github.com/artificemachine/superharness/actions/workflows/tests.yml)
[![PyPI version](https://badge.fury.io/py/superharness.svg)](https://badge.fury.io/py/superharness)
[![Python versions](https://img.shields.io/pypi/pyversions/superharness.svg)](https://pypi.org/project/superharness/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

**Multi-agent task coordination for Claude Code, Codex CLI, Gemini CLI, and OpenCode**

superharness lets AI coding assistants work on the same project without stepping on each other. It provides a shared contract (SQLite-backed), queue-based delegation, lifecycle rules, and handoff/ledger state so tasks survive across sessions and auto-manage themselves.

One command tells you the whole state of a project — agents, queue, discussions, and every task, in one screen:

```console
$ shux status
superharness status
project: ~/code/my-project
watcher: level=ok foreground (last heartbeat 9s ago)
heartbeat: ok (last heartbeat 9s ago)
inbox: pending=0 launched=0 running=2 paused=0 done=1655 failed=46 stale=0 stopped=0
retry-alert: threshold=3 high=46 ids=inbox-001,auto-eab0b7,auto-9db89b
approvals: pending=1
discussions: active=1 consensus=0 failed_participant=21 deadlock=0 closed=12
tasks: archived=10254 done=6 review=0 todo=2 in_progress=2 plan=1 failed=0 blocked=0 waiting_input=0

Active Tasks:
  feat-auth-rotation   in_progress   claude-code   (dispatched 4m ago)
  fix-migration-drift  plan_proposed owner         (awaiting approval)

No issues found. All clean.
```

`shux status --fix` cleans orphans and stale items; `shux status --check` exits non-zero for CI.

## Install as Claude Code Plugin

```
/plugin marketplace add artificemachine/superharness
/plugin install superharness
```

Gives you `/shux` (raw CLI passthrough), `/shux-contract`, `/shux-status`, `/shux-delegate`, `/shux-doctor`, `/shux-close`, plus a skill that auto-routes plain-English task/status questions to the right command.

## What's New in the v1.80.x line

- **Harness adapter registry**: claude/codex/gemini/opencode dispatch routed through a single `Harness` protocol, with golden-parity tests proving byte-identical invocations
- **Transcript tailing + dual watchdog**: byte-offset live dispatch progress with persisted cursors, backed by idle-timeout + absolute-ceiling deadline enforcement from the event stream
- **Typed telemetry events**: dedicated events table (migration v31) with a background emitter and DB-heartbeat liveness (`is_fresh`)
- **Dependency hygiene**: CVE floors on `starlette`/`python-multipart`, a previously-undeclared `requests` dependency now declared, and `.github/dependabot.yml` for ongoing drift
- **Dashboard/CLI DB-path fix**: `dashboard-ui.py` now resolves `state.db` through the same XDG-aware `get_connection` as the CLI, closing a silent divergence bug between the two
- **5,000+ tests** preventing regressions across lifecycle, dispatch, and protocol state

---

## ⚡ 1-Minute Quickstart

**Why use superharness?** 
*   **Prevent Overlaps**: Different agents (Claude, Codex, Gemini, OpenCode) won't edit the same files at the same time.
*   **Persistent State**: If an agent crashes or hits a limit, the next one knows exactly where to pick up.
*   **Auto-Mode**: Lifecycle rules auto-archive stale tasks, auto-fail deadlines, auto-close consensus discussions, and auto-clean orphans.
*   **Full Visibility**: `shux status` gives a complete health dashboard in one command.

### 1. Install
```bash
pipx install superharness
```

### 2. Initialize
Inside your project:
```bash
shux onboard
```

### 3. Start the Guardian
```bash
# Start background watcher (Headless default)
shux operator start

# Start with dashboard (always-on UI)
shux operator start --dashboard
```

### 4. Dashboard UI
```bash
# Launch on-demand UI (with auto-timeout)
shux dashboard
```

### 5. Check health
```bash
shux status          # Full health dashboard
shux status --fix    # Auto-clean orphans, stale items, consensus discussions
shux status --check  # CI mode (exit 1 if issues found)
```

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
curl -fsSL https://raw.githubusercontent.com/artificemachine/superharness/main/src/superharness/scripts/install-remote.sh | bash
# export PATH="$HOME/.local/bin:$PATH"  # add to ~/.zshrc or ~/.bashrc if needed
```

Or clone manually:
```bash
git clone https://github.com/artificemachine/superharness.git ~/.local/share/superharness
cd ~/.local/share/superharness && pip install -e .
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
shux continue          # resume active contract: next resumable task + recommended action
shux delegate <id>     # create task + enqueue in one step (task must be plan_approved or later)
shux test-type <id>    # set mandatory test types for a task
shux verify <id>       # record verification result (pass/fail)
shux close <id>        # mark done (task must be report_ready or review_passed); use --cancel-remaining --cancel-reason "..." to bulk-cancel open subtasks and close atomically; --force bypasses all gates
shux subtask-cancel    # cancel a single subtask with a mandatory reason (--task <id> --sub <sub-id> --reason "...")
shux task create       # create a task with --blocked-by, --tdd-red/green/refactor, --criteria flags
shux task status       # update task lifecycle status (todo → plan_proposed → plan_approved → in_progress → report_ready → done)
shux status            # dashboard: tasks, watcher, profile
shux recall <keywords> # search past handoffs and ledger (hits >14d old get a staleness caveat; tune with --max-fresh-days)
shux distill           # distill recent handoffs+ledger into curated project lessons (--dry-run/--apply/--schedule)
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

### Intelligence layer

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
📚 **[Docs index](docs/README.md)** — Every active doc, by topic
🔍 **[Audit trail](docs/audits/)** — Self-audit reports, including findings against this repo

---

## Auditing itself

superharness is used to audit superharness. Reports live in
[`docs/audits/`](docs/audits/) and are kept whether or not they are flattering —
an audit trail that only records passes is not an audit trail.

Findings from the [2026-07-20 pass](https://github.com/artificemachine/superharness/blob/54f52220/docs/audits/2026-07-20-job-ready-v2.md), all
since fixed, give a sense of what these catch:

- **The CI security scan had silently stopped running.** `shipguard` was pinned to
  a version that raised `SyntaxError` at import on the pinned Python, and the step
  piped through `tee` under `bash -e` — no `pipefail` — so the job took `tee`'s
  exit status and reported success while scanning nothing.
- **A DNS-rebinding path to the dashboard.** The CSRF check derived its expected
  origin from the request's own `Host` header, so the comparison always matched.
- **A path-traversal id could reach `shutil.rmtree`** via the dispatch worktree path.
- **A migration guard that could detect corruption but never prevent it** — it ran
  its integrity check after the transaction had already committed.

Each was reproduced with a failing test before being fixed. The `/job-ready`
pipeline that produced the report is a slash command, not part of this package.

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

- `python3` 3.11+ — `pip install superharness` (or `uv sync --dev` for a dev checkout). Runtime deps: `click`, `pyyaml`, `ruamel.yaml`, `pydantic`, `fastmcp`, `requests` — installed automatically.
- `bash` — only needed for macOS/Linux watcher service install scripts; not required on Windows or for any core commands
- `claude` CLI (for Claude delegation commands): `npm install -g @anthropic-ai/claude-code`
- `codex` CLI (for Codex delegation commands): `npm install -g @openai/codex`
- macOS `launchd` or Linux `systemd` for background watcher (see Platform Support); `--foreground` mode works everywhere

---

## Project Runtime State

**SQLite is the sole runtime source of truth.** All task, discussion, handoff, ledger, and dispatch state lives in one `state.db` file:

```text
~/.local/state/superharness/<project-hash>/state.db   # XDG path (new projects)
.superharness/state.sqlite3                            # legacy path (pre-XDG projects)
```

Every read and write goes through `shux`/`superharness` — never hand-edit the database or its exports directly.

`.superharness/` itself holds project config plus **export-only** YAML artifacts, regenerated from SQLite on demand and safe to delete:

```text
.superharness/
├── contract.yaml          # exported snapshot of tasks, decisions, failures
├── handoffs/              # exported session handoff notes
├── ledger.md              # exported append-only event log
├── decisions.yaml         # exported cross-agent ADRs
├── failures.yaml          # exported failure memory
└── inbox.yaml             # exported dispatch queue snapshot
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
├── src/superharness/scripts/  # installers (launchd/systemd/remote), delegate/watcher shell scripts, dashboard UI
├── scripts/               # dev-reinstall + L5 verification loop scripts
├── docs/                  # architecture and user guide
├── tests/                 # unit/integration/e2e tests
└── CHANGELOG.md
```

---

## Security Note

The background watcher enables **unattended execution** (agents run without human supervision). This is powerful but requires explicit confirmation:

**macOS (launchd):**
```bash
bash src/superharness/scripts/install-launchd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30 \
  --confirm-non-interactive yes \
  --confirm-skip-permissions yes
```

**Linux (systemd):**
```bash
CONFIRM_NON_INTERACTIVE=yes bash src/superharness/scripts/install-systemd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30
```

**Read the full threat model:** [SECURITY.md](SECURITY.md)

---

## Prior art and influences

superharness draws on ideas from several open agent harnesses and patterns. Each link points to the specific extraction or comparison doc.

- [Nous Research / hermes-agent](https://github.com/nousresearch/hermes-agent) — agent lifecycle and tool-use shape. See [docs/AUDIT-pi-hermes-adaptation.md](docs/AUDIT-pi-hermes-adaptation.md), [docs/archive/COMPARISON-superharness-vs-pi-hermes.md](docs/archive/COMPARISON-superharness-vs-pi-hermes.md), [docs/hermes-integration-tdd-plan.md](docs/hermes-integration-tdd-plan.md)
- [earendil-works/pi](https://github.com/earendil-works/pi) — multi-agent coordination patterns
- [obra/superpowers](https://github.com/obra/superpowers) — composable `SKILL.md` files, two-stage review (spec compliance, then code quality), TDD enforcement. See [docs/CONCEPT-superpowers-extraction.md](docs/CONCEPT-superpowers-extraction.md)
- [paperclipai/paperclip](https://github.com/paperclipai/paperclip) — adapter breadth, plugin SDK shape, dashboard control plane. See [docs/AUDIT-paperclip-gap-analysis.md](docs/AUDIT-paperclip-gap-analysis.md)
- [Charlie85270/Dorothy](https://github.com/Charlie85270/Dorothy) — parallel-agent Kanban UI, SQLite FTS5 knowledge store. See [docs/archive/comparison-dorothy.md](docs/archive/comparison-dorothy.md)
- [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) — per-agent persistent memory plugin for Claude Code. Inspired our privacy-tag write boundary, env-driven multi-profile isolation, observation snapshot table, and citation URL pattern (not auto-prompt-injection, which fights operator gating). See [docs/AUDIT-claude-mem-adaptation.md](docs/AUDIT-claude-mem-adaptation.md), [docs/CONCEPT-claude-mem-integration.md](docs/CONCEPT-claude-mem-integration.md), [docs/PLAN-claude-mem-integration.md](docs/PLAN-claude-mem-integration.md)
- **Ralph Loops** ([Chris Parsons workshop](https://youtu.be/2TLXsxkz0zI), [Jeffrey Huntley](https://ghuntley.com/)) — "next most important task" dispatch, sub-agent validation against confirmation bias, fresh-context discipline

See [ATTRIBUTIONS.md](ATTRIBUTIONS.md) for the full extract list — what each source contributed, and what we deliberately did not adopt.

---

## Current Version

Current version: see the [PyPI badge](https://pypi.org/project/superharness/) above — 5,000+ tests, harness adapter registry, transcript tailing, dual watchdog, typed telemetry events.

See [CHANGELOG.md](CHANGELOG.md) for the full iteration log.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE).
