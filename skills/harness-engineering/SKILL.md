---
name: harness-engineering
description: Meta-principles for building and maintaining the AI development harness
triggers:
  - harness
  - workflow optimization
  - tool setup
  - new skill
  - meta
  - why this framework
---

# Harness Engineering

The harness determines whether the model's intelligence translates into useful work. The model is a brain in a jar — the harness gives it hands, feet, and memory.

## Core Thesis

Same Claude model scored **78%** on the CORE benchmark inside Claude Code's harness vs **42%** inside a different harness (Small Agents). Same brain, different body, nearly double the performance. This isn't prompt engineering — it's structural.

Source: Anthropic presentation at AI Engineer Summit, January 2026. Documented in vault: `claude_code_vs_codex_the_decision_that_compounds_every_week_you_delay_that_nobod.md`

## What The Harness Controls

The harness is everything except the model weights:
- **Where** the AI works (your machine vs cloud sandbox)
- **What** it can touch (filesystem, tools, MCP servers)
- **What** it remembers between sessions (CLAUDE.md, progress files, git history)
- **How** it coordinates (sub-agents, delegation, isolation)
- **How** it fails (graceful recovery vs context corruption)

## Compounding Layers

Calvin French Owen's skill evolution shows how harness investment compounds:

```
Layer 1: /commit          → consistent commits
Layer 2: /worktree        → agents in separate work trees
Layer 3: /implement       → plan-then-execute pattern
Layer 4: /implement-all   → chained implementation calls
Layer 5: cross-agent      → Codex reviews Claude's work
Layer 6: full pipeline    → security → test → review → ship
```

Each layer builds on the previous one. Each is specific to the harness architecture. Switching harnesses resets this to zero.

## Your Stack's Harness

| Component | Role in Harness |
|-----------|----------------|
| CLAUDE.md / AGENTS.md | Institutional memory — agent starts at 80% context |
| Skills (this framework) | Reusable workflow patterns loaded just-in-time |
| MCP servers (Serena, Context7) | Tool integration — semantic search, live docs |
| Obsidian vault | Long-term compound knowledge (deposits via /upvault) |
| Cross-agent routing | Claude Code = collaborator, Codex CLI = contractor |
| Ship pipeline | Automated quality gates before anything merges |

## Principles

1. **Harness beats model.** A better model + your harness = automatic upgrade. Don't chase models.
2. **Skills are just-in-time context.** Agent sees skill names (50 tokens), reads full definition only when needed. Keep skills focused.
3. **Each skill should be one thing.** Composable primitives > monolithic workflows.
4. **Build layers, not tools.** /commit → /ship → cross-agent pipeline. Each layer compounds on the previous one.
5. **The vault is the long-term memory.** Skills handle workflow. The vault handles knowledge. Don't confuse them.
6. **Bash is all you need.** Unix primitives over custom tools. GitHub CLI > GitHub MCP (38 tools = 15,000 tokens of descriptions).

## When to Add a New Skill

Add a skill when:
- You've explained the same pattern to the agent 3+ times
- A workflow has >3 steps that always happen in sequence
- You catch yourself copy-pasting instructions between sessions

Don't add a skill when:
- A bash alias would do
- The pattern is project-specific (put it in project CLAUDE.md instead)
- You're building a tool that already exists

## Anti-Patterns

- Building custom tools when bash one-liners work
- Loading all skills at session start (context bloat)
- Duplicating CLAUDE.md content in skills (single source of truth)
- Adding skills for things you do once a month (overhead > value)
- Switching harnesses because a new one looks shiny (resets compounding to zero)
