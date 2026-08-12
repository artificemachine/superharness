# Lean Feature Hierarchy

Keep the capabilities, but reduce the default product surface to about **10–12 command groups**.

## Core product

- `onboard` / `init`
- `status` / `doctor`
- `task`
- `contract` / `context` / `continue`
- `delegate`
- `handoff`
- `verify` / `close`
- `operator`
- `recall`
- `config`

Core promise: **coordinate agent work safely across sessions.**

## Optional modules

- Discussions and consensus
- Auto-dispatch and scheduling
- Worktrees, fan-out, swarm
- Dashboard and TUI
- MCP and external integrations
- Profiles, distillation, operator memory
- Analytics, benchmarks, Langfuse
- Notifications

Expose these through `shux enhance`, not the default help.

## Merge or hide

- Merge `heartbeat`, `pulse`, and `agent-pulse`.
- Merge `dashboard`, `dashboard-ui`, `dashboard-list`, and `dashboard-kill`.
- Merge `handoff`, `handoff-write`, and `handoff-generate`.
- Prefer `operator`; hide the overlapping `daemon` and `watch` mechanics.
- Group migration and export commands under a coherent state-management surface,
  while keeping recovery and portability operations discoverable.
- Keep `shux explain` as the single explanation command; remove the `why` and
  `wtf` aliases from the CLI.

Target: preserve functionality while reducing the visible CLI from 80+ commands to roughly 12 coherent groups.
