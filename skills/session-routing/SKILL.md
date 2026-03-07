---
name: session-routing
description: Route tasks to the correct agent and execution mode before starting work
triggers:
  - new task
  - task assignment
  - session start
  - "what should I use for"
---

# Session Routing

Before executing any task, classify it and route to the correct agent/mode.

## Routing Table

| Task Type | Agent | Mode | Reason |
|-----------|-------|------|--------|
| Interactive exploration, debugging, refactoring | Claude Code | Interactive session | Needs environment access, MCP, real-time feedback |
| Parallel batch work (multiple independent files) | Codex CLI | `codex --approval=auto-edit` | Sandboxed, safe for bulk generation |
| Code review of AI output | Cross-agent | Claude reviews Codex output (or reverse) | Different model catches different bugs |
| Documentation, vault notes, learning synthesis | Cowork | Desktop session | Obsidian MCP, browser agent, file management |
| Quick one-off questions, API lookups | Claude Code | Single prompt | Don't spin up a loop for a 30-second answer |

## Decision Process

1. **Classify the task** — What type of work is this?
2. **Check dependencies** — Does it need MCP servers? File access? Sandboxing?
3. **Route** — Match to the table above
4. **Confirm** — State the routing decision before executing

## Rules

- One task per evening session. No context-switching.
- If a task needs both agents, plan the handoff explicitly.
- Quick questions (<30 seconds) go to Claude Code interactive, never Codex.
- Batch file generation (>3 independent files) goes to Codex CLI.
- Always prefer the simplest execution mode that works.

## Anti-Patterns

- Running Codex for interactive debugging (no environment access)
- Using Claude Code for bulk generation when files are independent
- Starting work without routing (leads to wrong tool, wasted tokens)
