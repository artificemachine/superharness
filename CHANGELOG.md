# superharness — Iteration Log

This document is the full context for any agent (Claude Code, Codex CLI, Cowork, or any other LLM) continuing work on superharness. Read this first. It tells you what superharness is, how it got here, and where to push next.

---

## What Is superharness?

**Your personal harness architecture — the full operating environment that determines whether an AI model's intelligence translates into useful work for you, specifically.**

It is NOT a superpowers clone. It is NOT a skills plugin. It is the name, structure, and portability layer for the harness User has already built organically across the Claude config directory, Codex config directory, the DevOpsCelstn workspace, the Obsidian vault, and his own working patterns.

### Core thesis
Same Claude model scored 78% inside one harness and 42% inside another. Same brain, different body, nearly double the performance. The harness is a performance multiplier, not an optimization layer.

### Key distinction
- **obra/superpowers** = a generic skills plugin anyone installs. Teaches an agent how to work.
- **superharness** = a personal harness architecture. Teaches an agent how to work **with User**.

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

This session began with building two foundational documents for User:

1. **Developer Profile** (`maxime-roy-developer-profile.md`) — A comprehensive, honest assessment of who User is as a developer and entrepreneur. Includes:
   - 15+ years C++/Python/Rust/Solidity
   - 7,000 hours studying crypto, DeFi, staking, lending, TradingView, TFSA, ETF, macroeconomics over 5 years
   - Zimmer Biomet contract (C++/Qt/QML, medical devices)
   - new.blacc as main company entity, Cypher Farms separate (Proxmox infrastructure R&D, partnership)
   - 5-tier venture portfolio (VidDocs, Bear Crypto Club, CapCompare, Phraser, RepoSec)
   - Honest gaps: no shipped SaaS, no revenue, competitive markets
   - Anti-patterns ranked by likelihood: scope creep, over-planning, shiny object syndrome
   - Freedom number: $5K CAD/month intermediate, $12-16K+ full replacement

2. **Agent Context Document** (`maxime-roy-agent-context.md`) — An embeddable CLAUDE.md-style doc that tells any agent how to work with User specifically. Includes routing table, tech stack, session templates, protected files, anti-patterns.

3. **CLAUDE.md Template** (`CLAUDE-md-template.md`) — A generic/reusable template derived from the agent context doc, with HTML comment instructions.

### Key decisions made before superharness
- **Removed Ralph** (autonomous loop driver) from all documents. Reason: bottleneck is shipping, not coding speed. Token costs are real. Never used.
- **Removed @fix_plan.md** references — was Ralph-specific.
- **Added 7,000 hours crypto/finance** — major correction that changed the entire strategic analysis.
- **new.blacc established** as main company entity.
- **Proxmox partnership** clarified — co-operated with a friend.
- **Toned down hyperbole** — "most advanced solo-dev AI harness" replaced with honest assessment.

### The spark for superharness

User shared a vault note: transcript of Nate Herk's YouTube video "Claude Code vs Codex: The Decision That Compounds Every Week You Delay." Key insights absorbed:
- 78% vs 42% benchmark (harness > model)
- Calvin French Owen's workflow: Claude Code for planning, Codex for implementation, cross-agent review
- Compounding skill layers: /commit → /worktree → /implement → /implement-all
- Harness lock-in: switching resets compounding to zero

User then said: **"I want some kind of framework that I can include in my workflow."**

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

3. **What goes in templates/?** When User starts a new project, superharness should generate the right CLAUDE.md and AGENTS.md. How much is templated vs generated?

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

## Iteration 5 — Delivery Mechanism + Peer Review Model

**Date:** 2026-03-08
**Agent:** Cowork (Claude Opus 4.6)
**Session type:** Continued from iteration 4 (new session, context carried over via summary)

### Key Insight: superharness had no delivery mechanism

The existential question from iteration 4 ("is this project a harness?") had a clear answer: no, because it was a folder of docs no agent reads automatically. Superpowers works because of ONE thing — a SessionStart hook that injects content before Claude's first response. superharness had content but no delivery.

### How superpowers works (research)

Superpowers is a Claude Code plugin. Its entire mechanism:
1. `hooks/hooks.json` registers a SessionStart hook
2. `hooks/session-start.sh` reads the `using-superpowers` meta-skill
3. Wraps it in `<EXTREMELY_IMPORTANT>` tags, outputs dual-format JSON
4. Content injected into session before Claude says a word
5. Meta-skill tells Claude: "if 1% chance a skill applies, invoke it"

Personal skills live in `~/.config/superpowers/skills/` and shadow core skills.

### What was built

**Adapters** — the delivery mechanism per agent:

```
adapters/
├── claude-code/
│   ├── hooks/
│   │   ├── hooks.json          ← SessionStart hook config
│   │   └── session-start.sh    ← Injects identity + protocol awareness
│   ├── install.sh              ← Symlinks hooks into Claude Code
│   └── CLAUDE.md.template      ← Per-project CLAUDE.md generator
└── codex-cli/
    └── AGENTS.md.template      ← Per-project AGENTS.md generator
```

The Claude Code hook:
- Reads `identity/core.md` on every session start
- Detects active `.superharness/contract.yaml` in current project
- Checks for pending handoffs addressed to `claude-code`
- Injects everything as context before first response
- Works alongside superpowers — they inject skills, we inject identity + protocol

### Peer Review Model (user insight)

User clarification: Claude Code and Codex CLI are NOT architect/executor. They are **two senior devops/devsec engineers who challenge each other's work**. Both build AND review.

Protocol updated to support both patterns per-task:

**Pattern A: Peer Review** — both agents build different tasks, review each other's. Quality through mutual challenge. Used for security-critical or architecture-impacting work.

**Pattern B: Hierarchical** — one plans, one executes, one reviews. Speed through specialization. Used when architecture is clear and execution is the bottleneck.

**Pattern C: Subagent** — `codex exec` inside Claude Code session. Used for small isolated subtasks.

Contract format updated with `reviewer` and `role` fields per task. User (tech lead) decides which pattern per task.

### Agent Strengths & Weaknesses (NEW)

Added to protocol.md so each agent knows:
- Its own strengths and weaknesses
- What to watch for when reviewing the other's work

Claude Code: strong at reasoning/architecture/security, weak at over-engineering/verbosity/context rot
Codex CLI: strong at focused execution/testing/speed, weak at big picture/memory/complex reasoning
Ollama: strong at offline/free, weak at everything else (treat as junior dev)

### Files Created/Modified in Iteration 5

```
adapters/claude-code/hooks/hooks.json      ← NEW: SessionStart hook config
adapters/claude-code/hooks/session-start.sh ← NEW: identity injection script
adapters/claude-code/install.sh            ← NEW: symlink installer
adapters/claude-code/CLAUDE.md.template    ← NEW: per-project template
adapters/codex-cli/AGENTS.md.template      ← NEW: per-project template
agents/protocol.md                         ← UPDATED: peer review + hierarchical patterns, strengths/weaknesses
README.md                                  ← UPDATED: adapters in structure, v0.5
CHANGELOG.md                               ← UPDATED: this entry
```

### Iteration 5b — Plugin Format Fix (same session)

Research revealed that the original install.sh approach (symlink into `~/.claude/hooks/`) would **conflict** with superpowers — both would fight over the same `hooks.json` file. Claude Code's plugin system automatically merges hooks from all plugins, so the fix was to make superharness a proper Claude Code plugin.

**Changes:**
- Added `.claude-plugin/plugin.json` — plugin manifest
- Rewrote `hooks/hooks.json` to correct array format with `${CLAUDE_PLUGIN_ROOT}`
- Rewrote `install.sh` — now symlinks `adapters/claude-code/` into `~/.claude/plugins/superharness`
- Updated `session-start.sh` — uses `CLAUDE_PLUGIN_ROOT` env var (set by Claude Code) with fallback for manual testing

**How it works now:**
```bash
bash adapters/claude-code/install.sh
# Creates: ~/.claude/plugins/superharness → adapters/claude-code/
# Claude Code discovers it as a plugin, merges hooks with superpowers automatically
# Verify: /plugins in Claude Code should list superharness
# Uninstall: rm ~/.claude/plugins/superharness
```

**Files added/modified:**
```
adapters/claude-code/.claude-plugin/plugin.json  ← NEW: plugin manifest
adapters/claude-code/hooks/hooks.json            ← REWRITTEN: correct plugin format
adapters/claude-code/hooks/session-start.sh      ← UPDATED: CLAUDE_PLUGIN_ROOT support
adapters/claude-code/install.sh                  ← REWRITTEN: plugin symlink install
```

### Iteration 5 Open Questions

1. **Testing the plugin:** Need to test in a real Claude Code session. Does `/plugins` list superharness? Does the hook fire alongside superpowers? Does JSON output parse correctly?
2. **AGENTS.md generation:** The Codex template is static. Should there be a `generate.sh` that reads `identity/core.md` and outputs a project-specific AGENTS.md? Or is manual copy+edit sufficient?
3. **Naming:** User still questioning "superharness" as a name. Decision deferred.
4. **Marketplace:** Should superharness be published to a Claude Code marketplace (like superpowers uses obra/superpowers-marketplace)? Or keep it as manual git clone + install.sh?

---

## Iteration 6 — Enforcement Hooks, Review Lenses, Cross-Agent Memory

**Date:** 2026-03-08
**Agent:** Cowork (Claude Opus 4.6)
**Session type:** Continued from iteration 5 (same session)

### Research Findings

Deep web research on 2026 harness engineering. Full synthesis in `research/iteration-6-research.md`. Key findings:

- Claude Code now has 3-tier native memory (Auto Memory + Session Memory + CLAUDE.md) — don't duplicate it
- PreToolUse/PostToolUse hooks can enforce rules with teeth, not just documentation
- Specialized parallel review agents (9 lenses) outperform single-reviewer pattern
- Archgate CLI turns ADRs into CI/CD enforcement
- Claude-Mem plugin solves cross-session memory for Claude Code (but not Codex)
- Memory engineering now recognizes 4 types: working, procedural, semantic, episodic
- Industry protocols (A2A, OpenAI Agents SDK) validate our handoff pattern — ours is simpler (file-based)

### What Was Built

**1. Enforcement Hooks (PreToolUse + PostToolUse)**
The iteration 3b critique said superharness had "no enforcement, no teeth." Now it does:
- `scope-guard.sh` — PreToolUse on Write/Edit. Blocks .env/credentials/keys writes. Warns on system files.
- `branch-guard.sh` — PreToolUse on Bash. Blocks `git push` to main/master. Blocks force push. Warns on destructive git operations and `rm -rf /`.
- `ledger-append.sh` — PostToolUse on Write/Edit. Auto-appends file changes to `.superharness/ledger.md`. No manual logging needed.

**2. Review Lenses (`agents/review-lenses.md`)**
7 specialized review perspectives: security, architecture, performance, tests, error-handling, devops, api-contract. Assignable per-task in the contract via `review_lenses` field. Can run as parallel subagents or sequential checklist. Custom project-specific lenses supported in `.superharness/review-lenses/`.

**3. Cross-Agent Failure Store**
Redesigned `knowledge/failure-memory.md` with 3 tiers:
- Tier 1: Contract failures (short-lived, per-feature)
- Tier 2: `.superharness/failures.yaml` (persistent, cross-agent — both Claude and Codex read this)
- Tier 3: Vault (permanent, cross-project)

No longer duplicates Claude Code's native Auto Memory. Only stores what needs to cross to other agents.

**4. Cross-Agent Decision Store**
Redesigned `knowledge/decision-journal.md` with 3 tiers:
- Tier 1: Contract decisions (short-lived)
- Tier 2: `.superharness/decisions.yaml` (persistent ADR-lite format, cross-agent)
- Tier 3: Vault (permanent full ADRs)

Optional Archgate integration for enforcement via pre-commit hooks.

**5. Deprecated Files**
Replaced with hooks and native Claude Code features:
- `context/context-engineering.md` → DEPRECATED (Claude Code handles context natively)
- `context/anti-rot.md` → DEPRECATED (SessionStart hook re-injection solves this)
- `methodology/session-discipline.md` → DEPRECATED (replaced by enforcement hooks)

Files kept with deprecation notices pointing to replacements.

### Files Created/Modified in Iteration 6

```
adapters/claude-code/hooks/hooks.json      ← UPDATED: added PreToolUse + PostToolUse hooks
adapters/claude-code/hooks/scope-guard.sh  ← NEW: blocks credential writes, warns on system files
adapters/claude-code/hooks/branch-guard.sh ← NEW: blocks push to main, warns on destructive ops
adapters/claude-code/hooks/ledger-append.sh ← NEW: auto-logs file changes to ledger
adapters/claude-code/hooks/session-start.sh ← UPDATED: added review lenses + enforcement awareness
adapters/claude-code/CLAUDE.md.template    ← UPDATED: review lenses, failures/decisions awareness
adapters/codex-cli/AGENTS.md.template      ← UPDATED: review lenses, failures/decisions awareness
agents/protocol.md                         ← UPDATED: per-project structure + review_lenses in contract
agents/review-lenses.md                    ← NEW: 7 specialized review perspectives
knowledge/failure-memory.md                ← REWRITTEN: 3-tier cross-agent store
knowledge/decision-journal.md              ← REWRITTEN: 3-tier cross-agent store + Archgate
context/context-engineering.md             ← DEPRECATED
context/anti-rot.md                        ← DEPRECATED
methodology/session-discipline.md          ← DEPRECATED
research/iteration-6-research.md           ← NEW: full research synthesis
README.md                                  ← UPDATED: v0.6, new structure
CHANGELOG.md                               ← UPDATED: this entry
```

### Iteration 6 Open Questions

1. **Hook testing:** All hooks need real-world testing. Does scope-guard correctly parse JSON stdin? Does ledger-append handle all Write/Edit variants?
2. **Review lens subagents:** Can Claude Code spawn 7 parallel subagents for review? What's the token cost? Is sequential review sufficient?
3. **failures.yaml format:** Is YAML the right choice for cross-agent failure store? Codex CLI needs to reliably read/write it.
4. **Archgate integration:** Worth installing for decision enforcement? Or overkill for solo dev?
5. **Naming:** Still unresolved.

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

### User preferences (User / Rocha)
- Honest assessment over hype
- "Show before doing" — preview actions, wait for approval
- One task at a time, no context-switching
- Markdown by default unless code is needed
- Vault search before starting any new task (use Obsidian MCP if available)
- Minimal core, discoverable detail — don't load everything into context at once

---

## Iteration 7 — Cross-Agent Hardening, Identity Sanitization, and UX Simplification

**Date:** 2026-03-08  
**Agent:** Codex CLI (GPT-5)  
**Session type:** Multi-commit hardening + ship pipeline + user UX review follow-up

### What Was Delivered

1. **Inbox lifecycle and atomicity hardening**
- Replaced ad-hoc YAML mutation logic with structured helper operations in `scripts/inbox-yaml.rb`.
- Made dispatch claim transition atomic: `pending -> launched` plus `retry_count` increment and timestamp in one write.
- Added retry-limit enforcement inside helper transition.
- Added safe YAML parsing (`Psych.safe_load`) for inbox/state operations.

2. **Dispatch robustness improvements**
- Added dispatcher lock ownership tracking and safer lock release behavior.
- Stopped swallowing helper parsing errors as “no pending items.”
- Consolidated duplicated launch-failure handling into a single path.

3. **Inbox parser consolidation**
- Removed last awk-on-YAML contract parsing from enqueue path.
- Added helper subcommands:
  - `contract_task_exists`
  - `contract_task_project_path`
- Updated `inbox-enqueue.sh` to use helper subcommands.

4. **Lifecycle consistency cleanup**
- Removed `prepared` from active lifecycle docs and behavior.
- Standardized active lifecycle to: `pending -> launched -> running -> done|failed` (+ optional `stale`).
- Updated ROADMAP/architecture/readme references accordingly.

5. **Protocol hygiene improvements**
- Added/updated `check-contract-hygiene.sh` to use safe YAML loading in embedded Ruby.
- Removed redundant type checks.

6. **Identity and privacy sanitization**
- Removed personal identity/company details from active generated paths and hook context.
- Switched generated defaults to neutral owner language.
- Updated starter contract metadata from `created_by: maxime` to `created_by: owner`.

7. **User-flow fixes and UX polish**
- Fixed heredoc backtick command-substitution bug in `init-project.sh` (`\`...\`` escaped).
- Added warning when enqueueing unknown task IDs.
- Delegate scripts now emit handoff-aware prompts; if no handoff exists, they instruct contract-first execution.
- Preserved readable ISO timestamp strings across YAML round-trips.
- Added explicit prerequisites to README.
- Simplified generated `CLAUDE.md` / `AGENTS.md` defaults for first-time users (minimal core + advanced behavior note).
- Simplified README repo layout into operational vs reference directories.

8. **Repository cleanup**
- Removed deprecated `context/` files and cleaned stale references.
- Removed empty `templates/` directory.

### Tests and Validation

- Shell syntax checks passed on updated entrypoints.
- Ruby syntax checks passed for helper scripts.
- Unit tests extended and passing:
  - dispatch lifecycle/retry/priority coverage
  - malformed inbox behavior
  - enqueue contract-path validation
  - normalize archive behavior
- Full test suite executed during ship flow: **39 passed**.
- Security scan (`shipguard`) clean after fixes.

### Key Commits (Iteration 7)

- `3e0d1bc` — fix: make inbox dispatch atomic and parse YAML safely
- `14177a9` — fix: harden inbox lifecycle and atomic dispatch
- `a51ee91` — refactor: move enqueue contract parsing to Ruby helper
- `c3d5dc0` — refactor: tighten enqueue/dispatch and remove deprecated context docs
- `1dd2836` — fix: remove personal identity leakage and polish first-run UX
- `ac25d3e` — chore: harden protocol hygiene checks and refresh docs/tests
- `acbd711` — docs: simplify generated agent templates for first-time users

### Current Status

- Core cross-agent protocol (contract/handoff/ledger + inbox dispatch/watch) is stable and externally usable.
- Remaining work is mainly optional UX/productization polish, not correctness blockers.

---

## Iteration 8 — Security Hardening and Monitor Control Surface

**Date:** 2026-03-09
**Agent:** Codex CLI
**Session type:** Security hardening, CI pinning, and monitor UI control-surface review/fix loop

### What changed

1. **Inbox pipeline hardening**
- Moved inbox enqueue writes into the Ruby engine to avoid raw shell YAML appends.
- Replaced pipe-delimited dispatch item transport with JSON to prevent field-splitting corruption.
- Added strict token validation for task ids and inbox ids to block control-character and delimiter injection.
- Added regression coverage for newline, pipe, and malformed-id cases.

2. **CI supply-chain hardening**
- Pinned `shipguard` in GitHub Actions security workflow to `0.2.0` to avoid version drift in CI security scans.

3. **Browser monitor upgrade**
- Extended `monitor-ui` from a passive dashboard into an operations panel with:
  - dispatch preview for Claude/Codex
  - stale recovery retry
  - stale normalization
  - ledger tail and watcher log tails
  - optional Logdy deep-view launch

4. **Monitor security fixes**
- Added per-session auth token enforcement for all mutating monitor endpoints.
- Added origin/referer validation to block cross-site requests against localhost.
- Forced monitor binding to loopback-only hosts.
- Added `no-store` and defensive response headers for monitor responses.
- Added verified Logdy startup flow with port-in-use detection, readiness polling, and shutdown cleanup.
- Added a lock around Logdy launch to prevent duplicate concurrent starts.

### Tests and Validation

- Focused injection regression tests added and passing.
- Monitor HTTP/control-surface unit tests added and passing.
- Full unit suite executed after fixes: **57 passed**.
- Secret scan (`gitleaks`) clean.
- Replayed prior enqueue/dispatch injection probes and confirmed they are blocked.

### Key Commits (Iteration 8)

- `c321ade` — Harden inbox pipeline against YAML and delimiter injection
- `f0a0dcb` — Pin ShipGuard version in CI security workflow
- `a72b77e` — Harden monitor UI control surface

### Current Status

- Inbox enqueue/dispatch path is hardened against YAML injection and delimiter corruption.
- CI security workflow is pinned to a known ShipGuard version.
- Monitor UI now has a usable local operations surface with explicit security controls.

---

## Iteration 9 — Unattended Dispatch and Watcher Hardening

**Date:** 2026-03-09
**Agent:** Codex CLI
**Session type:** Audit-driven hardening pass for delegate, dispatch, watcher install, and scope guard flows

### What changed

1. **Dangerous unattended launch gating**
- Added separate explicit confirmation gates for:
  - `SUPERHARNESS_CONFIRM_NON_INTERACTIVE`
  - `SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS`
  - `SUPERHARNESS_CONFIRM_CODEX_BYPASS`
- `cli/delegate.sh` now refuses dangerous Claude/Codex unattended modes without the specific confirmation env var.

2. **launchd watcher safety**
- `install-launchd-inbox-watcher.sh` now validates `--interval` as a positive integer.
- launchd plist values are now XML-escaped before writing.
- watcher install now requires explicit confirmation flags before enabling unattended launch and dangerous bypass modes.
- `ensure-launchd-inbox-watcher.sh` and `reset-watcher-and-test.sh` now forward and validate the new confirmation options.

3. **Dispatch and inbox robustness**
- `engine/inbox.rb` now uses `Tempfile` for atomic writes instead of predictable PID-based temp files.
- `inbox-dispatch.sh` now:
  - retries lock reacquisition before failure reconciliation
  - marks failed items more reliably after launcher errors
  - validates target routing before item launch
  - avoids `readarray` so it no longer assumes Bash 4+
  - surfaces Ruby helper errors more directly
- `engine/contract.rb` now fails loudly on malformed handoff YAML instead of silently skipping it.

4. **Sensitive path guardrails**
- Expanded Claude scope guard to block writes to:
  - `~/.ssh/*`
  - `~/.kube/config`
  - `terraform.tfvars`, `*.tfvars`, `*.tfvars.json`

5. **Operator documentation**
- Added `SECURITY.md` documenting dangerous flags, confirmation env vars, and recommended watcher install modes.
- Linked the security guidance from the README.

### Tests and Validation

- Added unit coverage for:
  - delegate dangerous-flag confirmations
  - malformed handoff surfacing
  - launchd installer confirmation and plist escaping
  - dispatch lock-contention failure handling
  - expanded scope-guard sensitive path blocking
- Full unit suite executed after fixes: **67 passed**.
- `bash scripts/check-shell-entrypoints.sh` passed.
- `git diff --check` passed.

### Key Commit (Iteration 9)

- `50b7190` — Harden unattended dispatch and watcher flows

### Current Status

- Unattended Claude/Codex launch paths now require explicit per-risk confirmations.
- launchd watcher install no longer silently enables dangerous modes.
- Dispatch failure handling is more resilient under lock contention and malformed handoff input.
- Added pipeline-smoke-claude integration test (tests/integration/test_claude_watcher_pipeline.py) — verifies end-to-end watcher dispatch flow for claude-code target.

---

> **Note:** For release-oriented changelogs with semver tags, see [RELEASES.md](RELEASES.md).
> This file continues as the full iteration log.

---

> **Errata:** Earlier entries reference `DevOpsCelstn` — this was a local development workspace name used during early iterations. It has no significance to the project and has been removed from all source code.

---

## 2026-03-15 — shux monitor + shux test-type

### `shux monitor` — auto project detection + browser open

- `scripts/monitor-ui.py`: `--project` is now optional (defaults to cwd); added `--no-open` flag; browser opens automatically via `webbrowser.open()` on server start
- `src/superharness/cli.py`: `cmd_monitor_ui` auto-injects `--project <cwd>` when not supplied; shux help text updated

### `shux test-type` — mandatory test types on tasks

- New command `src/superharness/commands/test_type.py`: attaches a `test_types` list to a contract task
- Interactive numbered menu when called bare (proposes: unit, integration, e2e, manual, smoke)
- Non-interactive flags: `--set`, `--add`, `--remove`, `--show`
- Writes `test_types: [...]` atomically to `contract.yaml` via ruamel round-trip
- Registered in `cli.py` as `superharness test-type`; listed in `shux` help shortcuts
- `src/superharness/engine/validate.py`: `shux hygiene` warns on `done` tasks that have `test_types` without verified evidence

---

## 2026-03-15 — v0.9.4 — fix: shux installed as console script

- `pyproject.toml`: added `shux = "superharness.cli:main"` to `[project.scripts]`
- `shux` was documented and referenced throughout the codebase but never registered as a binary entry point — users who installed via pip/pipx had no `shux` command
- Both `superharness` and `shux` now resolve to the same CLI entrypoint on install

---

## 2026-03-15 — v0.9.5 — feat: auto-install watcher on macOS and show monitor URL at init

- `src/superharness/commands/init_project.py`: `shux init` now auto-installs the background watcher on macOS without requiring `--with-watcher`
- `--interactive` mode user answer still overrides the default
- Watcher tip message suppressed on macOS (no longer needed)
- Monitor UI URL (`http://127.0.0.1:8787`) printed at end of init output

---

## 2026-03-15 — v0.9.6 — feat: monitor auto-finds free port

- `scripts/monitor-ui.py`: `shux monitor` now scans ports 8787–8806 and binds the first free one when the default is occupied
- Prints `port 8787 in use, using 8788` when falling back
- Explicit `--port N` still errors clearly with no fallback
- Handles `EADDRINUSE` on macOS (errno 48) and Linux (errno 98)
- `tests/unit/test_monitor_ui.py`: 5 new unit tests covering skip-one, skip-many, all-busy, explicit-port error, and Linux errno path

---

## 2026-03-15 — v0.9.7 — fix: scripts included in pip/pipx installs

- `scripts/` moved to `src/superharness/scripts/` so it is included in built packages
- `pyproject.toml`: added `[tool.setuptools.package-data] superharness = ["scripts/*"]`
- `cli.py`, `inbox_dispatch.py`, `inbox_watch.py`: use `importlib.resources` to locate scripts — works correctly for both editable and pip/pipx installs
- `inbox_dispatch.py`, `inbox_watch.py`: respect `SUPERHARNESS_SCRIPTS_DIR` env var for test/CI overrides
- `.githooks/pre-commit`, `check-shell-entrypoints.sh`: updated paths
- All tests updated to reflect new script paths
- `check-contract-hygiene` test fixture: added `verified: true` to done task (pre-existing failure)
