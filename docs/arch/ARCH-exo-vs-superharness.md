# Exo vs. Superharness

Exo and Superharness are complementary, not substitutes: **Exo is an agent runtime; Superharness is a multi-agent control plane.** For this environment, Superharness should remain authoritative, with Exo only as a constrained execution backend.

| Dimension | Exo | Superharness |
|---|---|---|
| Primary job | Runs a long-lived, self-modifying agent | Coordinates multiple external coding agents |
| Core unit | Agent → conversation → turn | Contract → task → dispatch → handoff |
| Execution | Own model loop, tools, sandbox, scheduler and chat adapters | Launches Claude, Codex, Gemini and OpenCode CLIs |
| “Adapter” meaning | Discord, Slack, WhatsApp, Signal, ExoChat | Coding-agent harness/CLI integration |
| State | File-backed JSON event history | Transactional SQLite source of truth |
| Parallelism | Conversations, scheduled work, agent lineage | Isolated Git worktrees, fan-out, swarm and peer review |
| Autonomy | Very high; can rewrite and rebuild itself | Approval-gated lifecycle with verification and retries |
| Recovery | Sandbox snapshots and conversation rewind | Handoffs, failure classification, retry policies and stale-state reconciliation |
| Observability | Conversation/tool/adapter events | Fleet status, typed telemetry, heartbeats, transcript tailing and dashboard |
| Best fit | Persistent personal agent or experimental runtime | Reliable software-development orchestration |

The key architectural difference is that Superharness has the stronger coordination foundation. Its [SQLite state model](https://github.com/artificemachine/superharness#project-runtime-state) provides migrations, transactions, foreign keys and multi-process coordination. Exo’s file-backed state uses process-local locks, producing the races and message-loss paths found in the audit.

Exo has the richer agent-facing runtime: integrated tools, messaging channels, sandbox lifecycle and recursive self-improvement. Superharness intentionally does not implement those; it governs agents that already have them.

Security nuance: neither is an OS security boundary. Superharness relies on operator policy and application gates, but Exo’s default read-write source mount plus host guardian creates a direct prompt-injection-to-host path—substantially more dangerous.

## Recommended Composition

```text
Superharness — task authority, approvals, worktrees, verification, handoffs
      └── constrained Exo adapter — conversation runtime, tools, scheduling
```

Give each Exo dispatch a task-scoped worktree; disable its whole-repository self-mount, host guardian, arbitrary adapter paths and unauthenticated HTTP surface. Do not replace Superharness with Exo.
