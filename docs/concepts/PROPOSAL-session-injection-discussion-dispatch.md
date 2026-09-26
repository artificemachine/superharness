# PROPOSAL: Session Injection for Discussion Dispatch

## The Gap

The system uses a **file-based handshake**: agent writes a YAML → discussion sees it as a verdict. But the agents are launched as **one-shot subprocesses** (`opencode run "<prompt>"`) that exit in milliseconds without actually processing the task. The inbox item shows `done` because the dispatch process exited cleanly — not because any work happened.

```
Watcher → dispatch → opencode run "discuss..." → exits rc=0 → "done"  ❌
                                                         no YAML written
```

The agents aren't running as persistent daemons capable of receiving and processing tasks. They're spawned from scratch, get a prompt as CLI args, and immediately exit.

## Proposed Patch: Session Injection

Instead of spawning a new agent process, **inject the discussion task into the agent's active session** via a file-based trigger that the session hooks already support.

### How it works

1. Watcher detects a discussion task for agent X
2. Instead of `subprocess.Popen(agent binary)`, it writes a **prompt file** to `.superharness/discussions/<id>/round-N-<agent>.prompt.md`
3. The agent's existing session hook (`session-turn-end.sh` for claude-code, or equivalent) detects the file and surfaces the prompt
4. Agent responds in-session, writes the YAML, and the discussion system picks it up

### What changes

| File | Change |
|------|--------|
| `inbox_dispatch.py` | Add `--session-inject` mode. For discussion tasks, write `.prompt.md` instead of spawning a process. Set inbox to `dispatched` (not `done`). |
| `adapters/claude-code/hooks/session-turn-end.sh` | Check for `.prompt.md` files; if found, echo the prompt to stdout so the agent sees it |
| `adapters/opencode/` (new) | Mirror the claude-code hook pattern: detect `.prompt.md` and surface it |
| `discussion_dispatch.py` | When checking round completion, accept `dispatched` status as "in progress" alongside `pending`/`launched` |
| `inbox_watch.py` `_gc_discussion_deadlock` | Treat `dispatched` inbox items as still-active (not zombie) |

### Why this works

- **No new daemon needed** — uses the agent session already running
- **Leverages existing hook infrastructure** — claude-code's `session-turn-end.sh` already runs every turn
- **Backward compatible** — the YAML handshake remains the same; only the delivery mechanism changes
- **Detectable** — the watcher can see whether a `.prompt.md` was consumed (file mtime changes) vs ignored

### Effort: Medium (~3-4 files, ~100 lines)
