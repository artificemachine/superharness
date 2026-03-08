# superharness Architecture

## Thesis

superharness is the operating layer around AI agents: identity, protocol, routing, quality gates, and continuity. It is designed to make agent output reproducible and auditable across sessions and across agents.

## Eight Layers

| # | Layer | Question | Purpose |
|---|-------|----------|---------|
| 1 | Identity | WHO | Stable developer profile, constraints, anti-patterns |
| 2 | Agents | WHAT | Agent-specific adapters and shared protocol |
| 3 | Routing | WHERE | Task routing and delegation strategy |
| 4 | Discipline | WHEN | Session lifecycle and execution behavior |
| 5 | Quality | HOW GOOD | Security gates and review rigor |
| 6 | Knowledge | COMPOUNDS | Decision/failure memory that persists |
| 7 | Context | HOW MUCH | Context loading and anti-rot strategy |
| 8 | State | SURVIVES | Contract/handoff/progress continuity |

## Design Principles

- Minimal core, explicit extensions.
- Prefer executable safeguards over prose-only policy.
- Keep protocol files small, structured, and append-friendly.
- Optimize for real project flow, not harness self-complexity.
- Keep maintenance bounded after baseline reliability is achieved.

## System Components

1. Hooks (inside Claude Code session)
- Session context injection, scope guarding, branch safety, ledger append.

2. Protocol state (inside project `.superharness/`)
- `contract.yaml`, `handoffs/`, `ledger.md`, `failures.yaml`, `decisions.yaml`.

3. Dispatch pipeline
- `inbox-enqueue.sh` writes validated pending work.
- `inbox-dispatch.sh` selects by priority and transitions status.
- `inbox-watch.sh` polls and dispatches continuously.
- launchd install/ensure scripts run watcher in background on macOS.

## Status Model

Inbox item statuses:
- `pending`: queued and not yet processed
- `launched`: CLI launch attempted (retry budget incremented)
- `running`: optional external transition
- `done`: completed successfully
- `failed`: exhausted retries or launch failure
- `stale`: optional lifecycle marker

## Audience Split

- README: install/init/use and operational commands.
- This document: architecture and rationale.
