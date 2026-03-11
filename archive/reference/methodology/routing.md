# Routing Protocol — Layer 3

The dispatch logic that matches tasks to the right agent, the right model, and the right mode.

---

## Decision Table (Human-Readable)

Use this to decide execution mode before starting any task:

| Task Type | Agent | Mode | Why |
|-----------|-------|------|-----|
| Interactive exploration, debugging, refactoring | Claude Code | Interactive | Needs environment, MCP, real-time feedback |
| Parallel batch work (multiple independent files) | Codex CLI | `--approval=auto-edit` | Sandboxed, safe for bulk generation |
| Code review of AI output | Cross-agent | Claude reviews Codex (or reverse) | Different model catches different bugs |
| Documentation, vault notes, research synthesis | Cowork | Desktop session | Obsidian MCP, browser agent, file management |
| Quick one-off questions, API lookups | Claude Code | Single prompt | Don't spin up a loop for a 30-second answer |
| Architecture decisions, complex planning | Claude Code (Opus) | Interactive + sub-agents | Needs highest reasoning, context, tool access |
| Grunt work: formatting, renaming, boilerplate | Codex CLI (Haiku/Spark) | Batch | Cheap, fast, parallelizable |

---

## Model Escalation Protocol

Don't start with the most expensive model. Escalate based on need.

```
Level 1: Haiku / Codex Spark
  → Batch tasks, formatting, simple generation, boilerplate
  → Cost: lowest. Speed: fastest.
  → Escalate if: output quality insufficient or task requires reasoning

Level 2: Sonnet (default)
  → Most tasks. Interactive coding, debugging, implementation.
  → Cost: moderate. Quality: high for 90% of work.
  → Escalate if: Sonnet fails twice on the same task, or task is architectural

Level 3: Opus
  → Architecture decisions, complex multi-step reasoning, cross-agent coordination
  → Cost: highest. Use deliberately.
  → Rule: never use Opus for what Sonnet can handle. Check cost dashboard.
```

**The rule from CLAUDE.md global:** Opus only after Sonnet fails 2×. This is a budget discipline, not a quality preference.

---

## Orchestration Protocol (Agent-Executable)

As the harness matures, routing evolves from human decisions to agent-dispatched workflows.

### Level 1: Human Routes (current)
You decide which agent gets which task. The routing table above guides the decision.

### Level 2: Agent Suggests (near-term)
A `/route` command takes a task description and recommends the agent + model:
```
/route "refactor the authentication module"
→ Recommended: Claude Code (Sonnet), interactive mode
→ Reason: refactoring needs environment access + real-time feedback
→ Estimated tokens: ~50K. Cost: ~$0.15
```

### Level 3: Agent Dispatches (future)
Claude Code's Task sub-agent system or agent-mux dispatches work:
```
Main agent (Claude Code Opus): plans the work, breaks into tasks
  → Sub-agent 1 (Codex Sonnet): implement auth module
  → Sub-agent 2 (Codex Sonnet): implement tests
  → Sub-agent 3 (Claude Haiku): update documentation
  → Main agent: review all outputs, cross-check, merge
```

### Cross-Engine Pattern (agent-mux)
One CLI, one JSON contract, any engine:
- Claude Code spawns Codex workers for implementation
- Codex spawns Claude for planning or review
- GSD coordinator (Opus) dispatches nested workers of any model
- Each worker operates in its own worktree (git isolation)

---

## Routing Heuristics

When in doubt, use these rules:

1. **Time pressure?** Use Claude Code interactive. It's faster to iterate live.
2. **Multiple independent files?** Use Codex batch. Parallelism wins.
3. **Need to search vault or browse web?** Use Cowork. It has Obsidian MCP + browser.
4. **Reviewing AI output?** Use a DIFFERENT agent than the one that wrote it.
5. **Simple or repetitive?** Haiku/Spark. Save budget for hard problems.
6. **Don't know where to start?** Claude Code Sonnet, interactive. Explore first.

---

## Anti-Patterns

- **Using Opus for everything.** Cost adds up. Sonnet handles 90% of coding tasks.
- **Using Codex for exploration.** Codex is sandboxed — no MCP, no environment access. Use Claude Code to explore, Codex to implement.
- **Routing by habit instead of task type.** Check the table. The right agent for yesterday's task isn't always right for today's.
- **Skipping cross-agent review.** The agent that wrote the code is worst at reviewing it.
