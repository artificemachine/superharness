# superharness

**The system that sits between you and your AI agents.**

Not a plugin. Not a skills collection. Not a tool. superharness is your personal harness architecture — the full operating environment that determines whether an AI model's intelligence translates into useful work for you, specifically.

Same Claude model: **78%** inside one harness, **42%** inside another. Same brain, different body, nearly double the performance. The harness is the multiplier.

You've already built this harness — organically, over months. superharness is the name, the structure, and the portability layer for what already exists.

**superpowers teaches an agent how to work.**
**superharness teaches an agent how to work with you.**

---

## The Problem

Your harness is scattered across Claude config, Codex config, DevOpsCelstn, the Obsidian vault, your shell, and your head. No single source of truth. Not versionable. Not portable. Pieces rot independently. Get a new machine and you clone dotfiles — but the *harness* has no install script.

superharness fixes this.

---

## Eight Layers

| # | Layer | Question | What It Solves |
|---|-------|----------|---------------|
| 1 | **Identity** | WHO | Developer profile, anti-patterns, constraints — stable across all projects |
| 2 | **Agents** | WHAT | Cross-agent config parity — Claude Code + Codex CLI + Cowork |
| 3 | **Routing** | WHERE | Dispatch protocol — which agent, which model, escalation rules |
| 4 | **Discipline** | WHEN | Session management — evening/weekend templates, one-task rule |
| 5 | **Quality** | HOW GOOD | Security gates + architectural guardrails + cross-agent review |
| 6 | **Knowledge** | COMPOUNDS | Vault protocol + instinct-based learning — gets smarter over time |
| 7 | **Context** | HOW MUCH | Context engineering — anti-rot, token budgets, selective injection |
| 8 | **State** | SURVIVES | Progress files, handoff templates, session continuity across compaction |

---

## Design Principles

**Minimal core, maximal extensibility.** The identity core is ~30 lines. Everything else is discoverable via `@imports`, not preloaded into the context window. Inspired by pi.dev: adapt the harness to your workflow, never the reverse.

**Context is finite.** Past ~60% utilization, more context makes the agent worse. Every line in CLAUDE.md competes with your actual task for attention. If a line doesn't change agent behavior, delete it.

**Compound, don't accumulate.** /upvault deposits knowledge. /remember withdraws it. Instincts auto-detect patterns. The vault gets richer. Switching harnesses resets to zero.

**Agents orchestrate, humans route.** Start with a human decision table. Evolve toward agents dispatching agents. Model escalation: Haiku → Sonnet → Opus, based on task complexity.

---

## Structure

```
superharness/
├── identity/                          ← Layer 1: WHO
│   ├── core.md                        ← ~30 lines — the minimal identity kernel
│   ├── developer-profile.md           ← Full profile (imported when needed)
│   └── agent-context.md               ← Hub doc with @imports to other layers
│
├── agents/                            ← Layer 2: WHAT
│   ├── claude-code/
│   │   ├── CLAUDE.md.global           ← Model selection, cost guards
│   │   └── commands/                  ← /ship, /remember, /upvault...
│   └── codex-cli/
│       ├── AGENTS.md.global           ← Codex-native global rules
│       └── skills/                    ← ship, remember, upvault...
│
├── methodology/                       ← Layers 3-5: WHERE, WHEN, HOW GOOD
│   ├── routing.md                     ← Dispatch protocol + model escalation
│   ├── session-discipline.md          ← Evening/weekend templates
│   ├── ship-pipeline.md               ← Security + architectural guardrails
│   └── cross-agent-review.md          ← Review across agents
│
├── knowledge/                         ← Layer 6: COMPOUNDS
│   ├── harness-thesis.md              ← The 78% vs 42% thesis
│   ├── vault-protocol.md              ← /remember, /upvault, mid-session triggers
│   └── instinct-protocol.md           ← Auto-detected patterns (future)
│
├── context/                           ← Layer 7: HOW MUCH
│   ├── context-engineering.md         ← Write/Select/Compress/Isolate operations
│   └── anti-rot.md                    ← Compaction survival strategies
│
├── state/                             ← Layer 8: SURVIVES
│   ├── state-protocol.md              ← Progress files, handoff format
│   └── templates/
│       ├── handoff.yaml               ← Session transition template
│       └── progress.md                ← In-session state template
│
├── templates/                         ← Bootstrap for new projects
│   ├── CLAUDE.md.template             ← Generate per-project CLAUDE.md
│   └── AGENTS.md.template             ← Generate per-project AGENTS.md
│
├── research/                          ← Research notes per iteration
│   └── iteration-3-research.md        ← Web research synthesis
│
├── CHANGELOG.md                       ← Iteration log for cross-agent continuity
└── README.md                          ← This file
```

---

## What superharness IS NOT

- **Not superpowers.** superpowers is a generic skills plugin. superharness is your specific architecture.
- **Not a tool.** You don't run it. You work inside it. It's the environment.
- **Not finished.** Living system. Some layers are formalized, others are still in your head. That's fine.
- **Not a replacement for CLAUDE.md.** CLAUDE.md stays per-project. superharness generates and maintains those files.

---

## Current State: v0.3

Eight layers defined. Identity, methodology, knowledge, context, and state layers populated with docs. Research-backed by Anthropic's harness engineering papers, OpenAI's Codex patterns, pi.dev's minimal extensibility philosophy, and the 2026 agentic coding community's best practices. See CHANGELOG.md for full iteration history.
