# superharness — Iteration Log

This document is the full context for any agent (Claude Code, Codex CLI, Cowork, or any other LLM) continuing work on superharness. Read this first. It tells you what superharness is, how it got here, and where to push next.

---

## What Is superharness?

**Your personal harness architecture — the full operating environment that determines whether an AI model's intelligence translates into useful work for you, specifically.**

It is NOT a superpowers clone. It is NOT a skills plugin. It is the name, structure, and portability layer for the harness Maxime Roy has already built organically across the Claude config directory, Codex config directory, the DevOpsCelstn workspace, the Obsidian vault, and his own working patterns.

### Core thesis
Same Claude model scored 78% inside one harness and 42% inside another. Same brain, different body, nearly double the performance. The harness is a performance multiplier, not an optimization layer.

### Key distinction
- **obra/superpowers** = a generic skills plugin anyone installs. Teaches an agent how to work.
- **superharness** = a personal harness architecture. Teaches an agent how to work **with Maxime Roy**.

### Six layers

| # | Layer | What It Solves | State |
|---|-------|---------------|-------|
| 1 | **Identity** | WHO you are — stable context across all projects | Formalized in `identity/developer-profile.md` and `identity/agent-context.md` |
| 2 | **Agents** | WHAT each agent needs — cross-agent config parity | Partially built — `agents/claude-code/` and `agents/codex-cli/` exist but empty |
| 3 | **Routing** | WHERE tasks go — dispatch logic | Described in README, not yet its own doc |
| 4 | **Discipline** | WHEN and HOW LONG — session management | Described in README, not yet its own doc |
| 5 | **Quality** | HOW GOOD — verification gates | Old skill files exist in `skills/` from v0 |
| 6 | **Knowledge** | WHY IT COMPOUNDS — vault deposit/withdrawal | `methodology/harness-thesis.md` written, vault protocol not yet |

---

## Iteration 0 — The Conversation That Started It All

**Date:** 2026-03-07
**Agent:** Cowork (Claude Opus 4.6)
**Session type:** Extended multi-hour conversation, continued from a previous session

### What happened before superharness

This session began with building two foundational documents for Maxime Roy:

1. **Developer Profile** (`maxime-roy-developer-profile.md`) — A comprehensive, honest assessment of who Maxime is as a developer and entrepreneur. Includes:
   - 15+ years C++/Python/Rust/Solidity
   - 7,000 hours studying crypto, DeFi, staking, lending, TradingView, TFSA, ETF, macroeconomics over 5 years
   - Zimmer Biomet contract (C++/Qt/QML, medical devices)
   - new.blacc as main company entity, Cypher Farms separate (Proxmox infrastructure R&D, partnership)
   - 5-tier venture portfolio (VidDocs, Bear Crypto Club, CapCompare, Phraser, RepoSec)
   - Honest gaps: no shipped SaaS, no revenue, competitive markets
   - Anti-patterns ranked by likelihood: scope creep, over-planning, shiny object syndrome
   - Freedom number: $5K CAD/month intermediate, $12-16K+ full replacement

2. **Agent Context Document** (`maxime-roy-agent-context.md`) — An embeddable CLAUDE.md-style doc that tells any agent how to work with Maxime specifically. Includes routing table, tech stack, session templates, protected files, anti-patterns.

3. **CLAUDE.md Template** (`CLAUDE-md-template.md`) — A generic/reusable template derived from the agent context doc, with HTML comment instructions.

### Key decisions made before superharness
- **Removed Ralph** (autonomous loop driver) from all documents. Reason: bottleneck is shipping, not coding speed. Token costs are real. Never used.
- **Removed @fix_plan.md** references — was Ralph-specific.
- **Added 7,000 hours crypto/finance** — major correction that changed the entire strategic analysis.
- **new.blacc established** as main company entity.
- **Proxmox partnership** clarified — co-operated with a friend.
- **Toned down hyperbole** — "most advanced solo-dev AI harness" replaced with honest assessment.

### The spark for superharness

Maxime shared a vault note: transcript of Nate Herk's YouTube video "Claude Code vs Codex: The Decision That Compounds Every Week You Delay." Key insights absorbed:
- 78% vs 42% benchmark (harness > model)
- Calvin French Owen's workflow: Claude Code for planning, Codex for implementation, cross-agent review
- Compounding skill layers: /commit → /worktree → /implement → /implement-all
- Harness lock-in: switching resets compounding to zero

Maxime then said: **"I want some kind of framework that I can include in my workflow."**

---

## Iteration 1 — The superpowers Clone (Wrong Direction)

**What was built:** A direct clone of obra/superpowers structure — `.claude-plugin/plugin.json`, `hooks/session-start.sh`, `skills/` directory with 7 SKILL.md files:
- session-routing, cross-agent-review, ship-pipeline, vault-sync, evening-session, weekend-block, harness-engineering

**What was wrong:** This was just superpowers with different content. A skills plugin, not a harness architecture. The user correctly called this out:

> "the goal was not to create a copy of superpowers"

**Lesson:** Skills are ONE component of a harness. The harness is the entire system — identity, agents, routing, discipline, quality, knowledge. Superpowers addresses skills. Superharness addresses everything.

---

## Iteration 2 — Naming the Architecture (Current State)

**What changed:**
1. Deep research into the vault — found the user already has:
   - Full cross-agent parallel setup documented (`codex-claude-parallel.md`)
   - AGENTS.md vs CLAUDE.md compatibility guide (`agents-md-guide.md`)
   - Global CLAUDE.md with model selection decision tree, cost guards (`claude_md_global.md`)
   - Matching slash commands ↔ Codex skills (/ship ↔ ship, /remember ↔ remember, etc.)
   - `goclaude` alias that launches clean sessions (`cd DevOpsCelstn && ./clean_context.sh && claude`)
   - 100+ shell aliases in `.zshrc`
   - Security audit of obra/superpowers in vault

2. Realized: **the harness already exists. It's scattered.** superharness is the framework that gives it a name, a structure, and portability.

3. Defined six layers (Identity, Agents, Routing, Discipline, Quality, Knowledge)

4. Rewrote README as a manifesto — not "here's a plugin" but "here's what your harness IS"

5. Wrote `methodology/harness-thesis.md` — the philosophical core (78% vs 42%, two philosophies, Calvin French Owen pattern, compounding chain, what it means for a solo dev)

6. Created `identity/` directory with developer-profile.md and agent-context.md (copied from workspace)

7. Created `agents/claude-code/` and `agents/codex-cli/` directories (empty — to be populated with global configs)

8. Created `methodology/` directory with harness-thesis.md

9. Created `templates/` directory (empty — for project bootstrap templates)

**What still exists from Iteration 1 (needs cleanup):**
- `skills/` directory with 7 SKILL.md files — these are valid workflow patterns but should be reorganized under `methodology/` or kept as a separate component
- `hooks/session-start.sh` — still useful but needs updating to match new architecture
- `.claude-plugin/plugin.json` — still references old skills-only structure
- `install.sh` — outdated, references old structure

### Iteration 2 File Inventory

```
superharness/
├── README.md                              ← v2 manifesto
├── CHANGELOG.md                           ← This file
├── identity/
│   ├── developer-profile.md               ← Copied from workspace
│   └── agent-context.md                   ← Copied from workspace
├── agents/
│   ├── claude-code/                       ← EMPTY — needs global CLAUDE.md, commands
│   └── codex-cli/                         ← EMPTY — needs global AGENTS.md, skills
├── methodology/
│   └── harness-thesis.md                  ← Written (78% vs 42%, compounding)
├── templates/                             ← EMPTY — needs CLAUDE.md and AGENTS.md templates
├── context/                               ← Legacy from between iterations (duplicates identity/)
│   ├── developer-profile.md
│   └── agent-context.md
├── skills/                                ← FROM ITERATION 1 — valid content, wrong framing
│   ├── session-routing/SKILL.md
│   ├── cross-agent-review/SKILL.md
│   ├── ship-pipeline/SKILL.md
│   ├── vault-sync/SKILL.md
│   ├── evening-session/SKILL.md
│   ├── weekend-block/SKILL.md
│   └── harness-engineering/SKILL.md
├── hooks/
│   └── session-start.sh                   ← FROM ITERATION 1 — needs update
├── .claude-plugin/
│   └── plugin.json                        ← FROM ITERATION 1 — needs update
├── install.sh                             ← FROM ITERATION 1 — outdated
└── knowledge/                             ← Created but EMPTY
```

### Iteration 2 Open Questions

1. **Should skills/ stay as a subdirectory?** The skill files have valid content (routing table, ship pipeline, session templates). They could live under `methodology/` as plain markdown, or stay as Claude Code-compatible SKILL.md files. Trade-off: SKILL.md format is directly loadable by Claude Code. Plain markdown is more portable.

2. **What goes in agents/?** The global CLAUDE.md and AGENTS.md already exist on the user's machine in their respective config directories. Should superharness contain copies (portable, versionable) or references (single source of truth)?

3. **What goes in templates/?** When Maxime starts a new project, superharness should generate the right CLAUDE.md and AGENTS.md. How much is templated vs generated?

4. **How does superharness relate to DevOpsCelstn?** The user's `goclaude` alias points to the DevOpsCelstn directory. Is superharness a subdirectory inside DevOpsCelstn, or is DevOpsCelstn part of the harness?

5. **Cleanup:** The `context/` directory duplicates `identity/`. The old `install.sh` and `.claude-plugin/plugin.json` reference the iteration 1 structure. These need cleaning.

6. **Vault integration:** The vault protocol (how /remember and /upvault work) is described in the README but not formalized in its own document yet.

7. **Is superharness a git repo?** If yes, it becomes versionable, cloneable, and the compounding thesis becomes literally true — every commit is a deposit. If no, it stays as a local directory structure.

---

## Iteration 3 — Research-Backed Architecture Expansion

**Date:** 2026-03-07
**Agent:** Cowork (Claude Opus 4.6)
**Session type:** Continued from iteration 2 (same session)

### Research Phase

Deep web research across 12+ sources. Full synthesis in `research/iteration-3-research.md`. Key sources:

- Anthropic — "Effective Harnesses for Long-Running Agents" (initializer + coding agent pattern, progress files)
- Anthropic — "Effective Context Engineering for AI Agents" (Write/Select/Compress/Isolate operations)
- OpenAI — "Harness Engineering" (AGENTS.md as table of contents, not encyclopedia; architectural guardrails)
- pi.dev / Mario Zechner — minimal core + extensible everything (4 core tools, session trees, mid-session model switching)
- everything-claude-code / affaan-m — instinct-based learning (auto-detect patterns, confidence scores)
- agent-mux / buildoak — cross-engine subagent orchestration (one CLI, one JSON contract, any engine)
- Continuous-Claude-v3 — ledger + handoff state management (YAML handoffs, pre-compaction hooks)
- HumanLayer — CLAUDE.md best practices (~60 lines, @imports, every line must change behavior)
- 2026 Agentic Coding Trends Report — multi-agent is table stakes (8 tools shipped parallel agents in Feb 2026)

### What Changed (6 → 8 layers)

**Layers 1-4: Refined**
- Layer 1 (Identity): NEW `identity/core.md` — ~30 line minimal kernel. Agent-context.md rewritten as hub document (~50 lines) with @imports instead of 139-line monolith.
- Layer 3 (Routing): Expanded from human decision table to orchestration protocol with model escalation (Haiku → Sonnet → Opus) and agent-mux-style dispatch.
- Layer 4 (Discipline): Formalized as `methodology/session-discipline.md` with anti-pattern guards.

**Layer 5: Expanded**
- Ship pipeline now includes architectural guardrails (dependency direction, module boundaries, drift prevention) — inspired by OpenAI's Codex pattern (1M lines, 3 engineers).
- Cross-agent review protocol formalized as standalone doc.

**Layer 6: Expanded**
- Vault protocol now includes mid-session retrieval triggers (search vault DURING work, not just at bookends).
- Instinct protocol defined conceptually (auto-detect patterns) — implementation deferred to v0.4.

**Layer 7: NEW — Context Engineering**
- Anthropic's four operations: Write, Select, Compress, Isolate
- The 60% rule: past 60% context utilization, performance degrades
- Token budget discipline: CLAUDE.md under 200 lines, sub-agents return summaries
- Cache optimization: front-load stable context, keep CLAUDE.md stable mid-session

**Layer 8: NEW — State Protocol**
- Progress file triplet: plan.md + progress.md + tasks.md
- Handoff template (YAML) for session transitions
- Pre-compaction checkpointing protocol
- Session recovery protocol (read state files → continue)

### Design Principles Added
- **Minimal core, maximal extensibility** (from pi.dev)
- **Context is finite** — every CLAUDE.md line competes with your task for attention
- **Agents orchestrate, humans route** — evolve from decision table to dispatch protocol

### Files Created in Iteration 3
```
identity/core.md                    ← NEW: ~30 line identity kernel
identity/agent-context.md           ← REWRITTEN: hub document with @imports (~50 lines)
methodology/routing.md              ← NEW: dispatch protocol + model escalation
methodology/session-discipline.md   ← NEW: evening/weekend templates + anti-pattern guards
methodology/ship-pipeline.md        ← NEW: security gates + architectural guardrails
methodology/cross-agent-review.md   ← NEW: cross-agent review protocol
knowledge/vault-protocol.md         ← NEW: /remember + /upvault + mid-session triggers
context/context-engineering.md      ← NEW: Layer 7 — Write/Select/Compress/Isolate
context/anti-rot.md                 ← NEW: Layer 7 — compaction survival strategies
state/state-protocol.md             ← NEW: Layer 8 — progress files + handoffs
state/templates/handoff.yaml        ← NEW: session transition template
state/templates/progress.md         ← NEW: in-session state template
state/templates/plan.md             ← NEW: current plan template
state/templates/tasks.md            ← NEW: remaining tasks template
research/iteration-3-research.md    ← NEW: full web research synthesis
README.md                           ← REWRITTEN: 8-layer architecture, minimal
```

### Legacy Files to Clean Up
Run this on the host machine (sandbox cannot delete):
```bash
cd superharness
rm -rf skills/ hooks/ .claude-plugin/ install.sh
rm context/agent-context.md context/developer-profile.md
```
These are iteration 1 remnants. Their content has been absorbed into the new methodology/ and identity/ directories.

---

## Current File Inventory (v0.3)

```
superharness/
├── README.md                              ← v3 (8 layers, minimal)
├── CHANGELOG.md                           ← This file
│
├── identity/                              ← Layer 1: WHO
│   ├── core.md                            ← ~30 lines — always loaded
│   ├── developer-profile.md               ← Full profile (on demand)
│   └── agent-context.md                   ← Hub document with @imports
│
├── agents/                                ← Layer 2: WHAT
│   ├── claude-code/                       ← TO DO: global CLAUDE.md, commands
│   └── codex-cli/                         ← TO DO: global AGENTS.md, skills
│
├── methodology/                           ← Layers 3-5: WHERE, WHEN, HOW GOOD
│   ├── routing.md                         ← Dispatch protocol + model escalation
│   ├── session-discipline.md              ← Evening/weekend templates + guards
│   ├── ship-pipeline.md                   ← Security + architectural guardrails
│   └── cross-agent-review.md              ← Review across agents
│
├── knowledge/                             ← Layer 6: COMPOUNDS
│   ├── harness-thesis.md                  ← The 78% vs 42% thesis
│   └── vault-protocol.md                  ← /remember, /upvault, mid-session triggers
│
├── context/                               ← Layer 7: HOW MUCH
│   ├── context-engineering.md             ← Write/Select/Compress/Isolate
│   └── anti-rot.md                        ← Compaction survival strategies
│
├── state/                                 ← Layer 8: SURVIVES
│   ├── state-protocol.md                  ← Progress files + handoff format
│   └── templates/
│       ├── handoff.yaml                   ← Session transition template
│       ├── progress.md                    ← In-session state
│       ├── plan.md                        ← Current plan
│       └── tasks.md                       ← Remaining tasks
│
├── templates/                             ← Bootstrap for new projects
│   ├── CLAUDE.md.template                 ← TO DO: per-project CLAUDE.md generator
│   └── AGENTS.md.template                 ← TO DO: per-project AGENTS.md generator
│
├── research/                              ← Research per iteration
│   └── iteration-3-research.md            ← Web research synthesis
│
└── [LEGACY — to delete]
    ├── skills/                            ← Iteration 1, absorbed into methodology/
    ├── hooks/                             ← Iteration 1, outdated
    ├── .claude-plugin/                    ← Iteration 1, outdated
    ├── install.sh                         ← Iteration 1, outdated
    └── context/{agent-context,dev-profile} ← Iteration 1 duplicates of identity/
```

---

## Open Questions for Next Iteration

1. **agents/ directory:** Should it contain copies of global CLAUDE.md/AGENTS.md (portable, versionable) or references/generators (single source of truth)?

2. **templates/ directory:** When bootstrapping a new project, how much of CLAUDE.md is templated vs generated from the harness? Should templates include Layer 7 context budgets?

3. **Instinct protocol implementation:** v0.3 defines the concept. v0.4 should implement at least the manual version (document patterns in per-project CLAUDE.md). Auto-detection is v0.5+.

4. **agent-mux integration:** Should routing.md include actual JSON contracts for cross-engine dispatch, or stay conceptual until agent-mux is installed?

5. **DevOpsCelstn relationship:** superharness lives at `DevOpsCelstn/harness/superharness`. Is this the right home? Should goclaude alias point to superharness?

6. **Hub document @imports:** Claude Code supports `@file` imports in CLAUDE.md. Should identity/agent-context.md literally use `@` syntax, or stay as prose references?

7. **Context budget enforcement:** Should there be a pre-commit hook or lint rule that checks CLAUDE.md line count? HumanLayer recommends <200 lines.

8. **Obsidian vault structure alignment:** superharness defines vault location rules. Do these match the current vault structure, or does the vault need reorganizing?

---

## Iteration 4 — Original Thinking + Cross-Agent Protocol

**Date:** 2026-03-08
**Agent:** Cowork (Claude Opus 4.6)
**Session type:** Continued from iteration 3 (new session, context carried over via summary)

### Self-Critique (iteration 3b)

Honest assessment: iteration 3 was mostly organized web research, not genuine innovation. 15 markdown files describing good intentions, nothing executable. Full critique in `research/iteration-3b-critique.md`. Seven problems identified:

1. It's a documentation project, not a system — no enforcement, no teeth
2. Doesn't solve the REAL bottleneck (shipping, not session efficiency)
3. Eight layers is too many for daily operation
4. Doesn't account for motivation decay (tired after day job)
5. Vault protocol is backwards (bolted on edges, not woven into work)
6. Cross-agent review is theater without metrics
7. No concept of "done" — infinite iteration risk (anti-pattern #2)

### Key Architectural Decisions

**superharness is agent-agnostic.** NOT a Claude Code plugin. Works across Claude Code, Codex CLI, Ollama, and any future LLM. This was a critical correction — previous iterations kept drifting toward Claude-Code-specific plugin structure.

**superharness complements obra/superpowers.** superpowers is a community Claude Code plugin (40K stars, not ours). superharness provides the personal layer superpowers can't — identity, cross-agent protocol, failure memory. Install both, they don't conflict.

**The `superpowers/` directory in harness/ was a mistake.** Created in iteration 1 as a misnamed clone. Should be deleted or replaced with an actual obra/superpowers install.

### Cross-Agent Communication Protocol (NEW — the real innovation)

Three file types that let ANY agent participate in a superharness workflow:

1. **Contract** (`contract.yaml`) — what needs to happen, task assignments, decisions, failures. One per feature. Any agent reads it to understand context, updates its own tasks.

2. **Handoff** (`handoffs/*.yaml`) — passing the baton between agents. Written by finishing agent, read by next agent. Includes what was done, what to check, what NOT to do.

3. **Ledger** (`ledger.md`) — append-only chronological log. One line per action. Any agent appends. This IS the session log.

Per-project instance: `.superharness/` directory in each project root.
Protocol definition: `agents/protocol.md` in superharness repo.

### Original Innovations (from critique)

Six ideas that no existing framework implements:

1. **Ship Pressure** — days-since-last-ship counter, visible at session start
2. **Energy-Based Routing** — route by developer energy level, not just task type
3. **5-Minute Session** — minimum viable session for low-energy days
4. **Failure Memory** — log what didn't work, auto-search before re-attempting
5. **Decision Journal** — auto-log WHY during work, not after
6. **Harness Scorecard** — monthly quantified self-assessment

### Files Created in Iteration 4

```
agents/protocol.md                  ← NEW: cross-agent communication protocol
knowledge/failure-memory.md         ← NEW: track what didn't work
knowledge/decision-journal.md       ← NEW: track WHY decisions were made
research/iteration-3b-critique.md   ← NEW: honest self-critique + original ideas
ROADMAP.md                          ← NEW: version targets + 1.0 definition
README.md                           ← UPDATED: agent-agnostic + superpowers relationship
```

### Iteration 4 Open Questions

1. **superpowers/ cleanup:** The fake superpowers directory in harness/ should be deleted or replaced with obra/superpowers install. Which?
2. **Contract format:** Is YAML the right format for contracts? Or would markdown be more accessible to all agents?
3. **Ledger vs vault:** The ledger is per-project, the vault is global. When does a ledger entry get promoted to a vault note?
4. **Agent-specific configs:** agents/claude-code/ and agents/codex-cli/ are still empty. What exactly goes there — generated CLAUDE.md/AGENTS.md, or instructions for generating them?
5. **Testing the protocol:** Which real project should be the first to use `.superharness/` ? VidDocs? RepoSec?

---

## Related Files Outside superharness

These documents were created in the same session and contain context relevant to superharness:

| File | Location | Relevance |
|------|----------|-----------|
| `maxime-roy-developer-profile.md` | Workspace root | Source for `identity/developer-profile.md` |
| `maxime-roy-agent-context.md` | Workspace root | Source for `identity/agent-context.md` |
| `CLAUDE-md-template.md` | Workspace root | Candidate for `templates/CLAUDE.md.template` |

## Vault Notes Referenced

| Note | Path | Relevance |
|------|------|-----------|
| Claude Code vs Codex transcript | `notes/1_ai/claude/claude_code_vs_codex_the_decision_that_compounds_every_week_you_delay_that_nobod.md` | Source for harness thesis (78% vs 42%, Calvin French Owen) |
| Codex-Claude parallel setup | `notes/1_ai/claude/tools_and_mcp/codex-claude-parallel.md` | Full cross-agent config reference |
| AGENTS.md guide | `notes/1_ai/claude/configuration/agents-md-guide.md` | Cross-agent compatibility protocol |
| Global CLAUDE.md | `notes/1_ai/claude/configuration/claude_md_global.md` | Model selection rules, cost guards |
| Superpowers security audit | `notes/1_ai/ai_specs/security_audit_report_spec_obra_superpowers.md` | Architecture reference for obra/superpowers |
| ClawdBot troubleshooting | `notes/1_ai/openclaw/clawdbot_troubleshooting_guide.md` | Skills installation patterns |
| zshrc configuration | `notes/1_infrastructure/zshrc_configuration_backup.md` | Shell aliases including goclaude |

---

## How to Continue

If you're an agent picking this up:

1. **Read this file first** — you now have full context of all iterations
2. **Read `identity/core.md`** — the minimal identity kernel (~30 lines)
3. **Read `identity/agent-context.md`** — the hub document that points to all layers
4. **Read `README.md`** — the 8-layer architecture overview
5. **Check the Open Questions above** — pick one and propose a direction
6. **Update this CHANGELOG** — add your iteration at the bottom

### Key files by purpose
- **Understanding the philosophy:** `knowledge/harness-thesis.md`
- **Understanding the research:** `research/iteration-3-research.md`, `research/iteration-3b-critique.md`
- **Understanding cross-agent work:** `agents/protocol.md` (the core innovation)
- **Understanding the methodology:** `methodology/routing.md`, `methodology/session-discipline.md`
- **Understanding context management:** `context/context-engineering.md`, `context/anti-rot.md`
- **Understanding state management:** `state/state-protocol.md`
- **Understanding what compounds:** `knowledge/failure-memory.md`, `knowledge/decision-journal.md`
- **Understanding the roadmap:** `ROADMAP.md` (what "done" looks like)

### User preferences (Maxime / Rocha)
- Honest assessment over hype
- "Show before doing" — preview actions, wait for approval
- One task at a time, no context-switching
- Markdown by default unless code is needed
- Vault search before starting any new task (use Obsidian MCP if available)
- Minimal core, discoverable detail — don't load everything into context at once
