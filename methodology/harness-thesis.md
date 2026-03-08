# The Harness Thesis

## The Number

Same Claude model. Identical weights. Identical training.
- **78%** on the CORE benchmark inside Claude Code's harness.
- **42%** inside a different harness (Small Agents).

Same brain, different body, nearly double the performance.

Source: Anthropic presentation at AI Engineer Summit, January 2026.

This isn't a marginal difference explained by prompt engineering. It's a structural difference explained by everything the harness does: how it manages context, how it hands off state between sessions, how it connects tools, how it verifies results.

## What This Means

The model determines how smart your AI is.
The harness determines whether that intelligence translates into useful work.

When a better model drops, it runs inside your harness automatically. You get the upgrade for free. But when you switch harnesses, everything resets — your CLAUDE.md files, your commands, your routing patterns, your institutional knowledge, your muscle memory. All of it goes to zero.

That's the lock-in nobody is pricing in. It's not vendor subscription lock-in. It's lock-in to a model maker's philosophy of how work should happen, as expressed through a harness.

## Two Philosophies

### Claude Code: The Collaborator
- Runs in your terminal, your shell, your environment
- "Bash is all you need" — composable Unix primitives over custom tools
- Memory lives in the agent: CLAUDE.md, progress files, Serena memory
- Sub-agents with shared task lists and dependency tracking
- The trust boundary is your entire workstation

### Codex CLI: The Contractor
- Runs in an isolated cloud container
- Your code is cloned in; internet access disabled by default
- Memory lives in the repo: AGENTS.md, documentation, linters-as-instructions
- Each task in its own sandbox — no cross-contamination
- Coordination through git branches, not shared state

Both solve the same problem — reliable work from an AI across many sessions — through genuinely different theories of where institutional knowledge should live.

## The Calvin French Owen Pattern

Calvin doesn't treat these as interchangeable tools. He treats them as complementary architectures:

1. **Claude Code for planning and exploration** — orchestrates terminal, explains codebase, spins up sub-agents, more creative in suggesting things the developer forgot
2. **Codex for implementation** — the code just straight up has fewer bugs
3. **Cross-agent review** — Codex reviews Claude's work and catches mistakes Claude missed

He picks his agent as a function of how much time he has and how long he wants it to run autonomously.

## The Compounding Chain

Calvin's workflow evolution shows how harness investment compounds:

```
Layer 1: /commit          → consistent commits
Layer 2: /worktree        → agents in separate work trees
Layer 3: /implement       → plan-then-execute pattern
Layer 4: /implement-all   → chained implementation
Layer 5: cross-agent      → one agent checks the other
Layer 6: full pipeline    → security → test → review → ship
```

Each layer builds on the previous. Each is specific to the harness architecture. Moving to a different harness doesn't mean learning new commands — it means rebuilding the entire compounding chain from scratch.

## What This Means for a Solo Dev

You have 10-20 hours per week. You can't afford a bad harness. A bad harness means:
- Re-explaining who you are every session
- Routing tasks to the wrong agent by gut feeling
- Skipping security scans when you're tired
- Starting new projects instead of shipping
- Losing session learnings because you didn't /upvault

A good harness means:
- Agent starts at 80% context before you type a word
- Routing is a decision table, not a feeling
- Quality gates are automatic, not optional
- Session discipline is structural, not willpower
- Knowledge compounds whether you're disciplined about it or not

That's what superreins is for.
