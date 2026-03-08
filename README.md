# superharness

**The system that sits between you and your AI agents.**

Not a plugin. Not a skills collection. Not a tool. superharness is your personal harness architecture — the full operating environment that determines whether an AI model's intelligence translates into useful work for you, specifically.

Same Claude model: **78%** inside one harness, **42%** inside another. Same brain, different body, nearly double the performance. The harness is the multiplier.

You've already built this harness — organically, over months. superharness is the name, the structure, and the portability layer for what already exists.

**superpowers teaches an agent how to work.**
**superharness teaches an agent how to work with you.**

### Agent-Agnostic

superharness is NOT a Claude Code plugin. It works across ALL your agents — Claude Code, Codex CLI, Ollama, whatever comes next. It defines a cross-agent communication protocol (contracts, handoffs, ledger) that any LLM can read and write. Agent-specific configs (CLAUDE.md, AGENTS.md, system prompts) are generated FROM superharness, not the other way around.

### Relationship to obra/superpowers

[obra/superpowers](https://github.com/obra/superpowers) is a community Claude Code plugin with generic skills. superharness complements it — superpowers provides community-maintained skills, superharness provides the personal layer (identity, methodology, cross-agent protocol) that superpowers will never have because it's generic. Install both. They don't conflict.

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
├── agents/                            ← Layer 2: WHAT + cross-agent protocol
│   └── protocol.md                    ← Cross-agent communication protocol
│
├── adapters/                          ← Delivery mechanism per agent
│   ├── claude-code/                   ← Claude Code plugin
│   │   ├── .claude-plugin/plugin.json ← Plugin manifest (auto-discovered by Claude Code)
│   │   ├── hooks/
│   │   │   ├── hooks.json             ← SessionStart hook config
│   │   │   └── session-start.sh       ← Injects identity + protocol on every session
│   │   ├── install.sh                 ← Symlinks plugin into ~/.claude/plugins/
│   │   └── CLAUDE.md.template         ← Per-project CLAUDE.md generator
│   └── codex-cli/
│       └── AGENTS.md.template         ← Per-project AGENTS.md generator
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
│   ├── failure-memory.md              ← Track what didn't work and why
│   └── decision-journal.md            ← Track WHY decisions were made
│
├── context/                           ← Layer 7: HOW MUCH
│   ├── context-engineering.md         ← Write/Select/Compress/Isolate operations
│   └── anti-rot.md                    ← Compaction survival strategies
│
├── state/                             ← Layer 8: SURVIVES
│   ├── state-protocol.md              ← Progress files, handoff format
│   └── templates/
│       ├── handoff.yaml               ← Session transition template
│       ├── progress.md                ← In-session state template
│       ├── plan.md                    ← Current plan template
│       └── tasks.md                   ← Remaining tasks template
│
│
├── research/                          ← Research notes per iteration
├── ROADMAP.md                         ← Version targets + 1.0 definition
├── CHANGELOG.md                       ← Iteration log for cross-agent continuity
└── README.md                          ← This file
```

### Per-Project Instance

When a project uses superharness, it gets a `.superharness/` directory:

```
my-project/
├── .superharness/
│   ├── contract.yaml              ← Active feature contract
│   ├── contracts/                 ← Archived completed contracts
│   ├── handoffs/                  ← Agent-to-agent handoff files
│   └── ledger.md                  ← Append-only activity log
├── CLAUDE.md                      ← Generated from superharness identity + methodology
├── AGENTS.md                      ← Generated from superharness identity + methodology
└── ...
```

---

## What superharness IS NOT

- **Not superpowers.** superpowers is a generic skills plugin. superharness is your specific architecture.
- **Not a tool.** You don't run it. You work inside it. It's the environment.
- **Not finished.** Living system. Some layers are formalized, others are still in your head. That's fine.
- **Not a replacement for CLAUDE.md.** CLAUDE.md stays per-project. superharness generates and maintains those files.

---

## Install

### Claude Code (plugin — coexists with superpowers)
```bash
bash adapters/claude-code/install.sh
# Verify: /plugins in Claude Code → superharness should appear
# Uninstall: rm ~/.claude/plugins/superharness
```
Hooks merge automatically with superpowers. Superpowers injects skills, superharness injects identity + protocol.

### Codex CLI (per-project)
```bash
cp adapters/codex-cli/AGENTS.md.template my-project/AGENTS.md
# Edit the {{placeholders}} with your project details
```

### Per-project protocol
```bash
mkdir -p my-project/.superharness/handoffs
touch my-project/.superharness/contract.yaml
touch my-project/.superharness/ledger.md
```

---

## Current State: v0.5

Eight layers defined. Claude Code adapter is a proper plugin with SessionStart hook — installs alongside superpowers with no conflicts. Codex CLI adapter provides AGENTS.md template. Cross-agent protocol supports peer review (two seniors challenging each other), hierarchical (plan → implement → review), and subagent (codex exec) patterns per-task. Agent strengths and weaknesses documented so each knows what to watch for when reviewing the other's work. See CHANGELOG.md for full iteration history.
