# superharness Architecture & Philosophy

**Why superharness exists, how it works internally, and the design decisions behind it.**

---

## Problem Statement

AI coding assistants (Claude Code, Codex CLI, Cursor, Aider, etc.) are powerful within a single session, but they lack memory and coordination across sessions. When you switch agents or return to a project days later, you lose context, duplicate work, and risk conflicts.

**Core problems superharness solves:**
1. **Session discontinuity** — No handoff state when switching agents or resuming work
2. **Agent collision** — Two agents can't safely work on the same project simultaneously
3. **Task amnesia** — What was done, why, and what's next is lost between sessions
4. **Queue coordination** — No way to delegate work to an agent without manual prompting
5. **Background execution** — Can't run agents unattended (e.g., nightly test runs)

---

## Design Philosophy

### 1. Durable protocol over ephemeral state

All coordination happens through **files on disk** (YAML, Markdown). No databases, no servers, no external dependencies.

**Why:**
- Works offline
- Git-compatible (all state is versioned)
- Human-readable (you can inspect and edit protocol files directly)
- Language-agnostic (Bash + Ruby for now, but any runtime can implement it)

### 2. Explicit handoffs over implicit state

Agents don't share memory. Instead, they **write handoffs** that the next agent reads.

**Handoff contains:**
- Task outcomes and artifacts
- Decisions made and why
- Blockers and dependencies
- Next steps

**Why:**
- Forces explicit context transfer
- Handoffs are versioned and auditable
- No invisible state or race conditions

### 3. Contract-first task coordination

A **contract** defines all tasks, their owners, dependencies, and status. Agents read the contract, claim a task, execute it, and update the contract.

**Why:**
- Single source of truth for what needs to be done
- Clear ownership (Claude vs Codex)
- Dependency tracking (task B waits for task A)
- Status visibility (todo → in_progress → done)

### 4. Queue-based dispatch, not polling

Agents don't poll for work. Instead, a **watcher** (launchd on macOS) monitors the inbox and dispatches work when tasks are enqueued.

**Why:**
- Low latency (dispatch within 30 seconds of enqueue)
- No busy-wait or CPU thrashing
- Unattended execution (night runs, CI integration)

### 5. Append-only ledger for auditability

All significant events (task started, task completed, handoff created) are appended to a **ledger** (`ledger.md`).

**Why:**
- Immutable history (no edits, no deletes)
- Easy to grep for "what happened when"
- Git diffs show new events only

### 6. Hygiene checks, not post-hoc cleanup

Protocol violations are caught **before commit** via hygiene checks and git hooks.

**Why:**
- Prevents bad state from entering the repo
- Enforces handoff/ledger discipline
- Fails fast instead of accumulating technical debt

---

## Runtime Layers

superharness is split into four operational layers:

### 1. `protocol/`
- Canonical cross-agent rules and templates.
- Source of truth for lifecycle and handoff expectations.
- YAML schemas and Markdown templates.

**Key files:**
- `protocol/spec.md` — protocol specification and lifecycle rules
- `protocol/templates/contract.yaml` — contract template
- `protocol/templates/handoff.yaml` — handoff template

### 2. `engine/`
- Ruby runtime for structured YAML operations.
- Queue transitions (`engine/inbox.rb`), contract queries (`engine/contract.rb`), and hygiene validation (`engine/validate.rb`).

**Why Ruby:**
- Strong YAML support (preserve comments, anchors, structure)
- Fast for small-scale ops (no JVM startup time)
- Good enough for CLI tooling (no need for compiled languages)

### 3. `cli/`
- Primary user-facing shell commands.
- Delegation, enqueue/dispatch/watch/recover, normalize, hygiene, and init wrappers.

**Key commands:**
- `cli/delegate.sh` — launch agent session with contract context
- `cli/enqueue.sh` — add task to inbox queue
- `cli/dispatch.sh` — claim next pending item and launch agent
- `cli/hygiene.sh` — validate protocol compliance

### 4. `scripts/`
- Backward-compatible shims for legacy entrypoints.
- launchd watcher install/ensure/uninstall.
- shell entrypoint integrity guard.
- stale launched-item recovery helper.

**Why separate from `cli/`:**
- `cli/` is the canonical API
- `scripts/` supports legacy workflows during migration
- Clear deprecation path (remove `scripts/` eventually)

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

### contract.yaml
Defines all tasks, their owners, dependencies, and status.

**Structure:**
```yaml
id: v07-readiness
created: 2026-03-10
created_by: owner
status: active
goal: "Drive superharness to v0.7"
tasks:
  - id: task-id
    title: "Task title"
    status: todo
    owner: codex-cli
    project_path: "/path/to/project"
decisions: []
failures: []
```

### handoffs/*.yaml
One file per task, created when a task is completed or suspended.

**Structure:**
```yaml
task_id: task-id
created: 2026-03-10T14:32:00Z
created_by: codex-cli
outcomes:
  - "Implemented feature X"
  - "Added tests in tests/test_feature.py"
decisions:
  - what: "Used pytest instead of unittest"
    why: "Better fixture support"
blockers: []
next_steps:
  - "Run integration tests"
```

### ledger.md
Append-only event log.

**Format:**
```markdown
- 2026-03-10 14:32 | task-id | done | codex-cli | Implemented feature X
- 2026-03-10 15:45 | test-task | in_progress | claude-code | Running tests
```

### decisions.yaml
Cross-agent architectural decision records (ADR-lite).

**Structure:**
```yaml
decisions:
  - id: "short-kebab-id"
    what: "decision title"
    why: "rationale"
    alternatives: ["alt1", "alt2"]
    date: 2026-03-10
    by: claude-code
    status: accepted
```

### failures.yaml
Cross-agent failure memory.

**Structure:**
```yaml
failures:
  - what: "pytest failed on Python 3.8"
    why_failed: "Missing typing_extensions backport"
    date: 2026-03-10
    agent: codex-cli
    tech: pytest
    severity: minor
    promoted: false
```

### inbox.yaml
Dispatch queue for pending work.

**Structure:**
```yaml
items:
  - id: "unique-item-id"
    task_id: task-id
    agent: codex-cli
    priority: 1
    status: pending
    created: 2026-03-10T14:00:00Z
    retry_count: 0
```

---

## Lifecycle Model

### Inbox status flow

```text
pending → launched → running → done
                           ↘ failed
                           ↘ stale
```

**Transitions:**
- `pending` → `launched` — dispatch claims item; retry count increments
- `launched` → `running` — agent begins work (session-start hook)
- `running` → `done` — agent completes task successfully
- `running` → `failed` — agent errors or aborts
- `launched` → `stale` — no status update within timeout (default 20 minutes)

**Stale recovery:**
- Items stuck in `launched` (never transitioned to `running`) are marked `stale`
- Recovery script (`cli/recover.sh`) can retry or archive stale items

### Task status flow

```text
todo → in_progress → done
                 ↘ blocked
                 ↘ failed
                 ↘ stopped
```

**Transitions:**
- `todo` → `in_progress` — agent starts work
- `in_progress` → `done` — task completed (requires handoff + ledger entry)
- `in_progress` → `blocked` — waiting on dependency or external input
- `in_progress` → `failed` — task failed (requires failure record)
- `in_progress` → `stopped` — task abandoned (requires reason + summary)

---

## Integration Surface

### Claude Code adapter

**Hooks:** `adapters/claude-code/hooks/`
- `session-start.sh` — inject contract context at session start
- `session-submit.sh` — append ledger entry on task completion

**Installation:**
```bash
bash adapters/claude-code/install.sh
```

Adds hooks to `~/.claude/settings.json`.

### Codex CLI adapter

**Templates:** `adapters/codex-cli/`
- `task-prompt.txt` — base prompt template
- `handoff-template.yaml` — handoff structure

**Dispatch:**
```bash
bash cli/delegate.sh --to codex-cli --project /path/to/project
```

Launches `codex` CLI with prompt from contract context.

### macOS background watcher

**Implementation:** `scripts/install-launchd-inbox-watcher.sh`

Installs a launchd agent that runs `superharness watch` every N seconds.

**Environment variables:**
- `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES` — required for unattended dispatch
- `SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES` — bypass permission prompts (danger)

**Security:**
- Watcher binds to loopback only (no remote access)
- Mutating actions require per-session token
- Logs written to `~/Library/Logs/superharness/`

---

## Design Decisions

### Why YAML, not JSON?

**YAML pros:**
- Human-readable (can edit in text editor)
- Preserves comments (important for protocol documentation)
- Supports anchors/references (DRY contract definitions)

**YAML cons:**
- Parsing complexity (Ruby's YAML is solid, but JS/Python parsers vary)
- Whitespace-sensitive (but so is Python)

**Decision:** YAML for protocol files, JSON for runtime interchange (e.g., hook output).

### Why Ruby, not Bash?

**Bash limitations:**
- No structured YAML support (would need `yq` or similar)
- No safe in-place YAML editing (would corrupt files)
- String-based parsing is fragile

**Ruby advantages:**
- First-class YAML support (preserve structure, comments)
- Fast enough for CLI ops (<100ms startup)
- Good stdlib for file ops, regex, process management

**Decision:** Ruby for YAML-heavy ops (`engine/`), Bash for orchestration (`cli/`, `scripts/`).

### Why append-only ledger?

**Alternatives considered:**
- Structured event log (JSON lines) — harder to read
- Git commit messages — not always granular enough
- Database — adds external dependency

**Append-only ledger wins:**
- Human-readable (Markdown)
- Git-friendly (diffs show new events only)
- Easy to grep (`grep "task-id" ledger.md`)
- Immutable (no edits, no deletes)

### Why inbox queue instead of cron?

**Cron limitations:**
- Fixed schedule (runs every N minutes, even if no work)
- No priority support
- No retry logic

**Inbox queue advantages:**
- Event-driven (dispatch only when work is enqueued)
- Priority support (high-priority tasks dispatched first)
- Retry logic (failed items can be retried)
- Status tracking (pending → launched → done)

**Decision:** Queue-based dispatch with launchd watcher (cron-like, but better).

### Why handoffs instead of shared memory?

**Shared memory risks:**
- Race conditions (two agents read/write same state)
- Invisible state (hard to audit)
- Coupling (agents must agree on memory format)

**Handoffs advantages:**
- Explicit context transfer (no invisible state)
- Immutable (handoff is written once, read many times)
- Auditable (handoffs are versioned in git)

**Decision:** Handoffs as first-class protocol artifact.

---

## Security Model

### Threat model

**In scope:**
- Unattended execution (watcher runs without human supervision)
- Arbitrary code execution (agents can run any command)
- Secrets exposure (agents may access API keys, tokens)

**Out of scope:**
- Multi-tenant isolation (superharness is single-user only)
- Network security (agents run locally, no remote API)

### Mitigations

**1. Confirmation gates for risky actions**
- Watcher requires `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES` for unattended dispatch
- Agents require `--confirm-skip-permissions` for permission bypass

**2. Monitor UI token protection**
- Mutating actions protected with per-session token
- Token printed to terminal on startup (not logged)

**3. Shell entrypoint validation**
- Explicit allowlist for executable scripts
- Shebang presence enforced
- Syntax validation (`bash -n`) on all shell scripts

**4. Protocol hygiene checks**
- Pre-commit hooks enforce handoff/ledger discipline
- Hygiene failures block git commit

---

## Performance Characteristics

### Latency

**Operation** | **Latency** | **Notes**
--- | --- | ---
`contract today` | <100ms | Ruby YAML parse
`enqueue` | <100ms | Append to inbox.yaml
`dispatch --print-only` | <200ms | Contract read + prompt render
`dispatch` (full) | 2-5s | CLI launch overhead
`hygiene` | <500ms | YAML validation + file scans
`watch` (loop) | 30s interval | launchd watcher default

### Scalability

**Metric** | **Limit** | **Notes**
--- | --- | ---
Tasks per contract | 100-200 | YAML parse time grows linearly
Handoffs per project | 500+ | File-based, no hard limit
Ledger lines | 10,000+ | Append-only, grep-friendly
Inbox items | 50-100 | Normalized regularly to archive

**Not designed for:**
- High-frequency dispatch (>10 tasks/minute)
- Multi-project coordination (each project is independent)
- Real-time collaboration (git-based, not live)

---

## Future Directions

### Planned (v0.8+)

- **Multi-agent voting** — require N agents to approve high-stakes decisions
- **Dependency-aware dispatch** — skip tasks with unmet dependencies
- **Handoff compression** — archive old handoffs to reduce repo size
- **Remote protocol sync** — push/pull protocol state to shared git remote

### Considered but rejected

- **Centralized server** — would break offline/git-native model
- **Real-time collaboration** — use operational transforms or CRDTs instead
- **Database backend** — YAML on disk is good enough for 99% of use cases

---

## Next Steps

- **User Guide:** [docs/GUIDE.md](GUIDE.md) — how to use superharness
- **Security:** [SECURITY.md](../SECURITY.md) — operational safety notes
- **Roadmap:** [ROADMAP.md](../ROADMAP.md) — current maturity target and next milestones
- **Changelog:** [CHANGELOG.md](../CHANGELOG.md) — version history
