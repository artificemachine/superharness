# Optional: MCP Memory Server

superharness includes automatic session persistence via the `session-stop` hook
(writes `.superharness/session-progress.md` on every session exit). For richer
cross-session memory with semantic search, you can optionally add an MCP memory
server.

## When to use

- You work primarily with Claude Code (single-agent workflow)
- You want searchable history across all past sessions
- You want automatic context compression (10x token efficiency)

The file-based approach (`session-progress.md` + handoffs + contract) is better
for **multi-agent** setups because Codex CLI can also read those files.

## Recommended: claude-mem

```bash
# Install globally
npm install -g claude-mem
```

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "claude-mem": {
      "command": "npx",
      "args": ["-y", "claude-mem"]
    }
  }
}
```

What it does:
- Auto-captures every tool invocation (input + output)
- Compresses and stores in local SQLite with full-text search
- Context from previous sessions automatically appears in new sessions
- ~10x token efficiency vs. manual context management

## Alternatives

| Server | Install | Storage | Notes |
|--------|---------|---------|-------|
| [claude-mem](https://github.com/thedotmack/claude-mem) | `npm i -g claude-mem` | SQLite | Most mature, auto-capture |
| [memory-mcp](https://github.com/yuvalsuede/memory-mcp) | `npm i -g memory-mcp` | `state.json` | Auto-updates CLAUDE.md |
| [mcp-memory-keeper](https://github.com/mkreyman/mcp-memory-keeper) | npm | Local files | Lightweight |
| [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | Go binary | Knowledge graph | 64 languages, sub-ms queries |

## How it works with superharness

MCP memory is **complementary**, not a replacement:

| Layer | Handles | Available to |
|-------|---------|-------------|
| **superharness** (file-based) | Task lifecycle, handoffs, decisions, failures | Claude Code + Codex CLI |
| **MCP memory** (optional) | Full session history, semantic search | Claude Code only |
| **Auto-memory** (MEMORY.md) | User preferences, project notes | Claude Code only |

## Verify installation

After adding the MCP server, run:

```bash
shux doctor
```

You should see:
```
INFO mcp:memory server configured (optional enhancement)
```
