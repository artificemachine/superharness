# shux — Operator Shortcuts

Agent-agnostic command reference for superharness. Works in Claude Code, Codex CLI, or any agent that reads this file.

When the user says any of the following, execute the described action immediately without asking for confirmation (except where noted).

All shortcuts use the `shux` prefix. Old long-form phrases (`contract today`, `continue contract`, etc.) still work but `shux` is canonical.

## Command Reference

| Phrase | Action |
|--------|--------|
| `shux init` | Run `superharness init --interactive --project .`; if `.superharness/` already exists, report current state |
| `shux doctor` | Run `superharness doctor --project .` — prereq + protocol health check. If watcher is not loaded, ask: "The background watcher is required and isn't running — would you like me to install it?" |
| `shux contract` | Read `contract.yaml`, render task table, suggest next task, offer to delegate cross-agent tasks |
| `shux continue` | Resume active contract and run the full session lifecycle automatically |
| `shux status` | Run `superharness status --project .` — dashboard: contract, tasks, watcher, profile |
| `shux monitor` | Run `superharness monitor-ui --project .` — open browser dashboard |
| `shux delegate <task_id>` | Create task (if missing) + enqueue in one step; never create without enqueueing |
| `shux close <task_id>` | Mark task done, append ledger line, write handoff YAML, stop |
| `shux recall <keywords>` | Run `superharness recall --project . --query "<keywords>"` — search past handoffs + ledger |
| `shux hygiene` | Run `superharness hygiene --project .` — validate protocol compliance (contract, handoffs, ledger) |
| `shux watch` | Run `superharness watch --foreground --project .` — start continuous watcher in foreground |
| `shux uninstall` | Run `superharness uninstall --project .` — remove watcher and system artifacts for this project |
| `shux update` | 1) `git pull` in the superharness repo to get latest, 2) re-run `superharness init` to refresh `CLAUDE.md`, `AGENTS.md`, and templates |
| `shux discuss` | If no subcommand given, ask: Topic (what to discuss), Owners (e.g. claude-code, codex-cli), optional ID — then run `superharness discuss start --project .`. Subcommands: `status`, `approve`, `start`, `rounds`, `consensus`, `list` |
| `shux help` | Run `superharness shux` — show all shux shortcuts in the terminal |

## Full Session Flow

```
shux init → shux doctor → shux contract → shux continue → shux close <id>
```

## Notes

- `shux delegate <task_id>`: always creates the task AND enqueues it. Never one without the other.
- `shux discuss` (no subcommand): prompt for Topic, Owners, optional ID before starting.
- `shux doctor` watcher warning: ask the user before installing — don't run automatically.
- All commands default to `--project .` (current directory).
