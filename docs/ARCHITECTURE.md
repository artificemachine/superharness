# superharness Architecture

**Why it exists, how it works, the decisions behind it.**

> **Legacy note (pre-SQLite migration).** This document predates the YAML→SQLite
> migration (v1.43+, completed v1.63). State now lives in SQLite at
> `.superharness/state.db`; the `.superharness/*.yaml` files described below are
> export/tombstone artifacts, not the source of truth. For the current state
> architecture see `AGENTS.md` ("State backend") and `engine/state_reader.py`.

---

## Problem

AI coding assistants are powerful within a session but lose context when you switch agents or return days later. superharness solves:

1. **Session discontinuity** — no handoff state between sessions
2. **Agent collision** — two agents can't safely work simultaneously
3. **Task amnesia** — what was done, why, and what's next is lost
4. **Queue coordination** — no way to delegate without manual prompting
5. **Background execution** — can't run agents unattended

---

## Design Principles

| Principle | Why |
|-----------|-----|
| **Files on disk, not a server** | Works offline, git-compatible, human-readable |
| **Explicit handoffs, not shared memory** | No invisible state, no race conditions, auditable |
| **Contract-first** | Single source of truth for tasks, owners, dependencies |
| **Queue-based dispatch** | Priority support, retry logic, status tracking |
| **Append-only ledger** | Immutable history, grep-friendly, git-native |
| **Hygiene before commit** | Catch violations early, not after the fact |

---

## Layers

```
cli/                    → user-facing shell commands (delegate, enqueue, dispatch, hygiene…)
src/superharness/engine/→ Python core: YAML ops, queue transitions, contract queries, validation
scripts/                → watcher install, launchd/systemd, guard scripts, dashboard-ui (with autohealth watchdog)
protocol/               → spec, templates, schema
adapters/               → Claude Code hooks, Codex CLI templates
```

**Python for `engine/`:** structured YAML support via PyYAML, fast startup. Bash handles orchestration; Python handles YAML and business logic.

**Key engine modules:**

| Module | Role |
|--------|------|
| `next_action.py` | **Core Heart**: Single source of truth for task state transitions and dispatch gates. |
| `operator.py` | **Guardian**: Self-healing stack manager for background Watchers and Dashboards. |
| `adapter_registry.py` | **Connector**: Registry of agent manifests (Claude, Codex, Gemini) with versioned model mapping. |
| `schemas.py` | Pydantic v2 models for all protocol YAML types. |
| `model_router.py` | Maps tier names (mini/standard/max) to agent-specific model IDs. |
| `orchestrator.py` | Opus-level orchestrator: decomposes tasks into subtasks. |
| `sdk_runner.py` | Wraps `claude_agent_sdk` for programmatic, headless Claude dispatch. |

## Headless-First Principle (v1.69.5+)

The core engine is decoupled from the UI. The Guardian runs only the background worker by default, reducing resource usage and preventing port/process leakage in headless environments. 

1. **Persistent Headless**: `shux operator start` (managed by `launchd`) ensures the task loop is always running without an HTTP server.
2. **On-Demand UI**: `shux dashboard` provides a temporary view with an **auto-timeout (lease pattern)** that shuts down the server if no user activity or heartbeats are detected.
3. **Opt-in Monitoring**: The `--dashboard` flag allows the Guardian to maintain a persistent UI instance if specifically requested.

---

## Runtime State (`.superharness/`)

```
state.db            SQLite — the source of truth for tasks, inbox, decisions, failures
handoffs/*.yaml     one file per task; written when a task completes or suspends
ledger.md           append-only event log
heartbeat.yaml      proactive watcher check config (config, not state)
profile.yaml        autonomy, primary_agent, team_size (config, written by install)

# Tombstone exports (generated from SQLite via `shux export-yaml`, NOT read as state):
#   contract.yaml, inbox.yaml, decisions.yaml, failures.yaml
```

---

## Lifecycle

**Inbox item:**
```
pending → launched → running → done
        ↘ paused              ↘ failed → stale (recover.sh)
```

**Task:**
```
todo → in_progress → done
                 ↘ blocked | failed | stopped
```

`paused` = skipped this cycle (dirty worktree or plan gate pending) — retried next cycle.

---

## Architecture Diagram

```mermaid
graph TB
    subgraph User
        CLI["superharness CLI"]
        Browser["Browser :8787"]
    end

    subgraph Scripts
        delegate["delegate.sh"]
        dispatch["inbox-dispatch.sh"]
        watch["inbox-watch.sh"]
        heartbeat["heartbeat.sh"]
        dashboard["dashboard-ui.py"]
    end

    subgraph Engine["src/superharness/engine/ (Python)"]
        inbox_py["inbox.py"]
        contract_py["contract.py"]
        profile_py["profile.py"]
        recall_py["recall.py"]
        orchestrator_py["orchestrator.py"]
        cost_estimator_py["cost_estimator.py"]
        subtask_agg_py["subtask_aggregator.py"]
    end

    subgraph State[".superharness/"]
        contract["contract.yaml"]
        inbox["inbox.yaml"]
        ledger["ledger.md"]
        handoffs["handoffs/*.yaml"]
    end

    subgraph Agents
        claude["Claude Code"]
        codex["Codex CLI"]
    end

    subgraph System
        launchd["launchd / systemd"]
        logs["~/Library/Logs/superharness/"]
    end

    CLI --> Scripts
    Browser -->|HTTP| dashboard
    launchd -->|every 15s| watch
    watch --> dispatch
    watch --> heartbeat
    dispatch --> delegate
    delegate --> claude
    delegate --> codex
    dashboard --> State
    claude --> State
    codex --> State
    Engine --> State
    Scripts --> Engine
```

---

## Key Design Decisions

**YAML not JSON** — protocol files need human-readable comments and can be edited directly. JSON is used for runtime interchange (hook output).

**Heartbeat ID allowlist** — `heartbeat.yaml` maps check `id` values to hardcoded commands in `heartbeat.sh`. The `command:` field is documentation only and never executed, preventing YAML injection.

**No database** — YAML on disk is sufficient for hundreds of handoffs and thousands of ledger lines. `superharness recall` uses grep-level search over handoffs — no embeddings needed.

---

## Agent Identity

For agents reading this: you are a coding agent working on behalf of the project owner — not a general-purpose assistant. Your job is to make forward progress on the current contract task with high precision and low blast radius.

**Operating constraints:**
- Ship > plan. One focused task per session.
- Keep changes within the current contract scope.
- Ask before touching files outside your assigned task's scope.

**Guardrails:**
- Never edit `.env`, credentials, secrets, or key files.
- Never push directly to main without human review.
- Run required checks before handoff or commit.
- If blocked, log the blocker in contract failures and stop — do not guess.

---

## See Also

- [GUIDE.md](GUIDE.md) — command reference
- [SECURITY.md](../SECURITY.md) — threat model and mitigations
- [INSTALL-AGENT.md](INSTALL-AGENT.md) — AI-driven install flow
