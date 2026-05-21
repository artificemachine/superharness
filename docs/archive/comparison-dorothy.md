# Dorothy vs Superharness

> Comparison as of 2026-03-20. Dorothy: github.com/Charlie85270/Dorothy

## At a glance

| | **Dorothy** | **superharness** |
|---|---|---|
| **What** | Desktop app (Electron) for parallel agent orchestration | CLI framework for serial agent handoff |
| **Agents** | 10+ running simultaneously | One at a time (serial dispatch) |
| **UI** | Full desktop app (Next.js/React) | Lightweight browser dashboard (:8787) |
| **Task system** | Kanban board (Backlog → Done) | Contract YAML + inbox queue |
| **Scheduling** | Cron-based | `scheduled_after`, `due_by`, `depends_on` |
| **Notifications** | Telegram + Slack (built-in) | Planned as modules (ntfy, telegram) |
| **Knowledge** | Vault (SQLite FTS5) | Obsidian vault + handoff files |
| **Automations** | GitHub/JIRA polling → auto-spawn agents | Watcher → inbox → dispatch |
| **Remote control** | Telegram/Slack commands (`/start_agent`) | Not yet |
| **Multi-agent** | Super Agent orchestrator via MCP | Contract + owner routing |
| **Worktrees** | Built-in git worktree support | Deferred |
| **Stack** | Electron, Next.js, TypeScript, SQLite | Python, YAML, shell scripts |
| **Install** | Desktop app download | `pip install`, zero deps |
| **Target** | Teams, enterprises | Solo devs |

## Where Dorothy is ahead

- **Parallel execution** — multiple agents working simultaneously across different codebases
- **Desktop GUI** — visual kanban, real-time terminal streaming per agent
- **Automations** — poll GitHub/JIRA, auto-spawn agents on new PRs/issues
- **Remote control** — Telegram/Slack bot built-in
- **Plugin ecosystem** — skills.sh marketplace, LSP plugins (TypeScript, Python, Rust, Go)
- **Enterprise integrations** — JIRA, Figma, Vercel, Google Workspace

## Where superharness is ahead

- **Lightweight** — no Electron, no SQLite, no React. Python + YAML files.
- **Session memory** — handoffs, ledger, decisions, failures survive across sessions. Tracks *why things failed* and *what was decided*, not just task status.
- **Protocol-first** — contract.yaml is the single source of truth. Any agent (Claude, Codex, future ones) can read it without coupling to a specific app.
- **Zero-config core** — `shux init` and you're running. No MCP servers, no database setup.
- **Portable** — works over SSH, in CI, headless servers. No desktop required.
- **Structured agent instructions** — Enqueue modal gives agents personalized TDD plans with context from plan docs, acceptance criteria, and prior failure reports.
- **Scheduling gates** — `depends_on` blocks dispatch until dependencies complete, `scheduled_after` for time-based gating.

## Different philosophies

Dorothy builds for **scale**: teams, parallel agents, enterprise integrations. The value proposition is "run many agents at once and orchestrate them visually."

Superharness builds for **depth**: solo dev, one agent at a time, but with rich context that compounds across sessions. The value proposition is "make one agent as effective as possible by never losing context."

They are complementary, not competitive. Dorothy answers "how do I run many agents at once?" Superharness answers "how do I make each agent session build on the last?"

## Features to watch from Dorothy

| Feature | Dorothy has it | Superharness status |
|---------|---------------|-------------------|
| Parallel dispatch + worktrees | Yes | Deferred (needs parallel dispatch first) |
| Telegram/Slack remote | Yes | Planned (mod.10-telegram) |
| GitHub automation (auto-spawn on PR) | Yes | Could be a module |
| Usage/cost tracking | Yes | Not planned |
| Super Agent orchestrator | Yes (MCP-based) | Not planned |

## Features Dorothy could learn from superharness

| Feature | Superharness has it | Dorothy equivalent |
|---------|-------------------|-------------------|
| Failure memory (decisions.yaml, failures.yaml) | Yes | No — vault stores docs, not failure context |
| Scheduling gates (depends_on, scheduled_after) | Yes | No — kanban is priority-based, not dependency-based |
| Personalized agent instructions per task | Yes (Enqueue modal + plan docs) | No — assigns tasks but doesn't shape approach |
| Handoff protocol (structured context for next session) | Yes | No — agents are long-running, not handed off |
| Append-only ledger | Yes | No |
