# Iteration 3 Research — Deep Web Synthesis

**Date:** 2026-03-07
**Agent:** Cowork (Claude Opus 4.6)
**Purpose:** Find everything that can improve superharness from the current state of the art.

---

## Sources Consulted

1. **Anthropic — "Effective Harnesses for Long-Running Agents"** (anthropic.com/engineering)
2. **Anthropic — "Effective Context Engineering for AI Agents"** (anthropic.com/engineering)
3. **Anthropic — 2026 Agentic Coding Trends Report** (8 trends reshaping software engineering)
4. **OpenAI — "Harness Engineering: Leveraging Codex"** (openai.com/index/harness-engineering)
5. **Martin Fowler — "Harness Engineering"** (martinfowler.com/articles)
6. **everything-claude-code** (affaan-m) — Anthropic hackathon winner, instinct-based learning
7. **agent-mux** (buildoak) — Cross-engine subagent orchestration
8. **Continuous-Claude-v3** — Ledger + handoff context management
9. **Claude Code Harness** (Chachamaru127) — Plan→Work→Review cycle
10. **HumanLayer — "Writing a Good CLAUDE.md"** — 60-line target, modular imports
11. **SFEIR / aiorg.dev / gend.co** — Claude Code best practices 2026
12. **Obsidian AI Second Brain guides** — Claude Code + Obsidian MCP compound knowledge

---

## Key Concepts That Are Missing from superharness

### 1. CONTEXT ENGINEERING AS A FORMAL LAYER

**What Anthropic defines:**
Four operations: Write, Select, Compress, Isolate.

- **Write** — externalize context to files when it's too large for the window
- **Select** — give agents ONLY the information relevant to their current step (RAG)
- **Compress** — sub-agents summarize before returning (not raw dumps)
- **Isolate** — each sub-agent gets lean context for its specific task

**What this means for superharness:**
We have a Knowledge layer (Layer 6) that handles vault deposits/withdrawals. But we don't have a **Context Engineering** discipline — the systematic practice of managing what goes INTO the context window at any given moment. This is arguably the highest-leverage skill a solo dev can build, because:

- Past ~60% context utilization, performance degrades ("context rot")
- Tool definitions + intermediate results consume tokens silently
- Compaction is lossy — it drops the "why" and keeps only the "what"
- Cache hit rate is the most important cost metric

**Proposal:** Add a **Layer 7: Context** or elevate context engineering into a cross-cutting concern across all layers.

---

### 2. PROGRESS FILE / STATE HANDOFF PROTOCOL

**What Anthropic discovered (long-running agents):**
The initializer + coding agent pattern:

1. An `init.sh` sets up the environment on first run
2. A `progress.txt` file keeps a running log of what agents have done
3. Every session reads progress, makes incremental progress, updates progress
4. Git history supplements the progress file

**Failure modes they identified:**
- Agent tries to do too much → runs out of context mid-feature → half-implemented, undocumented
- Later agent sees progress → declares job done prematurely
- Compaction doesn't pass clear instructions → next session is confused

**Community solution (Continuous-Claude-v3):**
- State via **ledgers** (structured state) and **handoffs** (YAML session transitions)
- Before compaction, auto-write handoff document
- Three files: `plan.md`, `context.md`, `tasks.md`

**What this means for superharness:**
We have /remember and /upvault for session bookends, but we're missing the **intra-session state management** — what happens during a long session when compaction hits. The harness thesis talks about compounding across sessions, but not about surviving WITHIN a session.

**Proposal:** Add a **state protocol** under methodology: progress files, handoff templates, pre-compaction hooks.

---

### 3. AGENTS.md AS TABLE OF CONTENTS, NOT ENCYCLOPEDIA

**What OpenAI discovered (1M lines of code, 1500 PRs, 3 engineers):**
- "Give Codex a map, not a 1,000-page instruction manual"
- AGENTS.md should be ~100 lines, acting as a table of contents
- Points to a structured `docs/` directory with design docs, specs, plans
- Progressive disclosure: agents discover context as needed

**What HumanLayer recommends:**
- Target under 200 lines per CLAUDE.md file, ideally ~60 lines
- Main file = table of contents with `@imports` pointing to detailed docs
- For each line, ask: "If I remove this, will Claude produce worse output?"
- Make rules specific and testable: not "handle errors properly" but "All async functions must have try/catch blocks"

**What this means for superharness:**
The current `identity/agent-context.md` is 139 lines and mixes WHO, HOW, WHAT, and WHERE. The README itself is 163 lines of manifesto. If superharness is supposed to generate per-project CLAUDE.md files, those need to follow the table-of-contents pattern — lean pointers, not encyclopedias.

**Proposal:** Restructure agent-context.md into a **hub document** (~60 lines) that `@imports` from identity/, methodology/, and agents/ rather than containing everything inline.

---

### 4. INSTINCT-BASED LEARNING (everything-claude-code)

**What affaan-m built (Anthropic hackathon winner):**
- An "instinct" system that automatically learns patterns from your coding behavior
- Commands to show learned instincts with confidence scores
- Import/export instincts between projects and people
- Instincts evolve/cluster into skills over time
- Three-phase code quality: auto-format (40-50% of issues) → structured JSON violations → subprocess fixes

**What this means for superharness:**
Our Knowledge layer (Layer 6) is about vault deposits (manual). Instincts are about **automatic pattern detection** — the harness gets smarter without you explicitly telling it to. This is the difference between a notebook (you write in it) and a learning system (it writes in itself).

**Proposal:** Consider an **instinct protocol** — patterns the harness learns from repeated behaviors (e.g., "you always run tests before committing in this project" → auto-suggest test run if you skip it). This could start as a simple log and evolve.

---

### 5. MULTI-AGENT ORCHESTRATION IS NOW TABLE STAKES

**What happened in Feb 2026:**
Every major tool shipped multi-agent in the same two-week window:
- Grok Build (8 agents)
- Windsurf (5 parallel)
- Claude Code Agent Teams
- Codex CLI (Agents SDK)
- Devin (parallel sessions)

**agent-mux pattern:**
- One CLI, one JSON contract, works with any engine
- GSD coordinator (Claude Opus) dispatches nested workers (Codex, Spark, Claude)
- Codex can spawn Claude as a sub-agent and vice versa

**What this means for superharness:**
Our Layer 2 (Agents) and Layer 3 (Routing) describe Claude Code vs Codex as a binary choice. But the state of the art is **orchestration** — one agent dispatching others, not a human manually choosing. The routing table should evolve from a human decision matrix into an agent-executable dispatch protocol.

**Proposal:** Evolve routing from a decision table into an **orchestration protocol** that agents can execute, not just humans can read. Include agent-mux-style JSON contracts.

---

### 6. CONTEXT ROT IS THE HIDDEN ENEMY

**Key numbers:**
- Past ~60% context utilization → performance degrades
- Claude Code window: ~200K tokens
- Compaction is lossy: 50-line architectural discussion → one sentence
- Tool definitions silently consume tokens
- Cache hit rate is the most important production metric

**Developer workarounds:**
- plan.md + context.md + tasks.md triplet
- Auto-handoff before compaction (YAML format)
- Pre-compaction hooks that checkpoint state
- Ledger systems (Continuous-Claude-v3)

**What this means for superharness:**
Our harness thesis talks about compounding. But compounding assumes continuity. Context rot breaks continuity. The harness needs an **anti-rot protocol** — specific practices that prevent context degradation during long sessions.

**Proposal:** Add anti-rot strategies to the methodology: progress file triplet, pre-compaction hooks, CLAUDE.md budget discipline (<200 lines), context checkpointing.

---

### 7. ARCHITECTURAL GUARDRAILS (OpenAI's Codex Pattern)

**What OpenAI enforces:**
- Dependency layers: Types → Config → Repo → Service → Runtime → UI
- Agents restricted to operate within layers
- Mechanical rules and structural tests enforce boundaries
- Result: 1M lines of code, ~1,500 PRs, 3 engineers

**What this means for superharness:**
Our Quality layer (Layer 5) focuses on security scans and cross-agent review. But it's missing **architectural guardrails** — rules that prevent agents from creating spaghetti across boundaries. For a solo dev building multiple projects, this is crucial: without guardrails, each agent session can introduce drift.

**Proposal:** Add architectural guardrails to the Quality layer — dependency direction rules, module boundary enforcement, structural tests.

---

### 8. OBSIDIAN AS ACTIVE PARTICIPANT, NOT PASSIVE STORAGE

**What 2026 guides recommend:**
- Claude Code + Obsidian MCP turns the vault into a **live workspace** (read, search, modify)
- At end of every session: create a new SOP and skill based on what you just did
- Over time, skill library grows into a personal automation system
- Smart Connections: RAG over your entire vault
- The vault compounds: every session makes Claude more personalized

**What this means for superharness:**
Our /upvault is a deposit. But the vault should also be an **active retrieval source during work**, not just at session start (/remember) and end (/upvault). Mid-session vault queries could prevent re-solving problems you've already solved.

**Proposal:** Extend the vault protocol to include **mid-session retrieval triggers** — specific moments when the harness should auto-search the vault (e.g., before implementing a pattern, before choosing a library, when hitting an error).

---

## Summary: What's Missing from superharness v0.2

| Gap | Current State | Proposed Fix | Priority |
|-----|--------------|-------------|----------|
| Context engineering | No formal discipline | Add Layer 7 or cross-cutting concern | **Critical** |
| Intra-session state | Only session bookends (/remember, /upvault) | Progress file triplet + handoff templates | **Critical** |
| CLAUDE.md bloat | agent-context.md is 139 lines, mixes concerns | Hub document with @imports, <200 lines | **High** |
| Instinct/learning | Manual vault deposits only | Instinct protocol — auto-detect patterns | **Medium** |
| Multi-agent orchestration | Binary routing table (human decides) | Agent-executable dispatch protocol | **High** |
| Context rot defense | Not addressed | Anti-rot protocol, pre-compaction hooks | **Critical** |
| Architectural guardrails | Security-only quality gates | Dependency layers, boundary enforcement | **Medium** |
| Vault as active participant | Bookend only (start/end) | Mid-session retrieval triggers | **High** |

---

## Proposed Layer Architecture v0.3

```
superharness v0.3 — Eight Layers

Layer 1: Identity     — WHO you are (stable, high-value-per-token)
Layer 2: Agents       — WHAT each agent needs (config parity)
Layer 3: Routing      — WHERE tasks go (dispatch protocol, not just table)
Layer 4: Discipline   — WHEN and HOW LONG (session management)
Layer 5: Quality      — HOW GOOD (security + architectural guardrails)
Layer 6: Knowledge    — WHY IT COMPOUNDS (vault protocol + instincts)
Layer 7: Context      — HOW MUCH (context engineering, anti-rot, token budgets)
Layer 8: State        — HOW IT SURVIVES (progress files, handoffs, continuity)
```

**Key evolution from v0.2:**
- Layers 1-4: refined, not restructured
- Layer 5: expanded (security → security + architectural guardrails)
- Layer 6: expanded (vault → vault + instinct-based learning)
- Layer 7: NEW — context engineering as a first-class discipline
- Layer 8: NEW — intra-session state management

---

### 9. PI.DEV — THE MINIMAL EXTENSIBLE HARNESS

**What pi.dev does differently (Mario Zechner / badlogic):**
- Only 4 core tools: read, write, edit, bash. Shortest system prompt of any major agent.
- Philosophy: "Adapt pi to your workflows, not the other way around"
- **Session tree**: Sessions stored as JSONL trees — you can navigate to any previous point and branch from there (/tree). History is a tree, not a line.
- **Extension architecture**: TypeScript extensions, skills, prompt templates, themes — bundled as npm/git packages
- **Mid-session model switching**: Use Claude for exploration, GPT for a second opinion, Gemini for large context — switch mid-session
- **Progressive feature building**: Deliberately omits sub-agents, plan mode, MCP from core — encourages you to build exactly what you need
- **Four modes**: interactive, print/JSON, RPC (process integration), SDK (embed in your apps)

**What this means for superharness:**
Pi's philosophy is deeply aligned with superharness: the harness adapts to you, not the other way around. But pi adds two concepts we're missing:

1. **Session tree branching** — sessions aren't linear. You should be able to branch from any checkpoint. Our state protocol (Layer 8) should account for tree-shaped session histories, not just linear handoffs.

2. **Minimal core + extensible everything** — pi proves you need LESS in the core system prompt and MORE in discoverable extensions. Our agent-context.md at 139 lines might actually be working AGAINST us by bloating the context window. The ideal might be: 30-line identity core + everything else as `@importable` extensions.

3. **Model-agnostic mid-session switching** — our routing table assumes you pick an agent at task start. Pi shows you can switch models mid-task. The routing layer should support model escalation (start with Haiku → escalate to Sonnet if stuck → escalate to Opus for architecture decisions).

---

## Summary: What's Missing from superharness v0.2

| Gap | Current State | Proposed Fix | Priority |
|-----|--------------|-------------|----------|
| Context engineering | No formal discipline | Add Layer 7 or cross-cutting concern | **Critical** |
| Intra-session state | Only session bookends (/remember, /upvault) | Progress file triplet + handoff templates | **Critical** |
| CLAUDE.md bloat | agent-context.md is 139 lines, mixes concerns | Hub document with @imports, <200 lines | **High** |
| Instinct/learning | Manual vault deposits only | Instinct protocol — auto-detect patterns | **Medium** |
| Multi-agent orchestration | Binary routing table (human decides) | Agent-executable dispatch protocol | **High** |
| Context rot defense | Not addressed | Anti-rot protocol, pre-compaction hooks | **Critical** |
| Architectural guardrails | Security-only quality gates | Dependency layers, boundary enforcement | **Medium** |
| Vault as active participant | Bookend only (start/end) | Mid-session retrieval triggers | **High** |
| Session branching | Linear handoffs only | Tree-shaped session history support | **Medium** |
| Minimal core principle | 139-line agent-context, 163-line README | 30-line identity core + discoverable extensions | **High** |
| Model escalation | Pick agent at task start, fixed | Dynamic model switching within routing | **Medium** |

---

## Proposed Layer Architecture v0.3

```
superharness v0.3 — Eight Layers

Layer 1: Identity     — WHO you are (stable, high-value-per-token)
Layer 2: Agents       — WHAT each agent needs (config parity)
Layer 3: Routing      — WHERE tasks go (dispatch protocol + model escalation)
Layer 4: Discipline   — WHEN and HOW LONG (session management)
Layer 5: Quality      — HOW GOOD (security + architectural guardrails)
Layer 6: Knowledge    — WHY IT COMPOUNDS (vault protocol + instincts)
Layer 7: Context      — HOW MUCH (context engineering, anti-rot, token budgets)
Layer 8: State        — HOW IT SURVIVES (progress files, handoffs, session trees)
```

**Key evolution from v0.2:**
- Layers 1-4: refined, not restructured
- Layer 5: expanded (security → security + architectural guardrails)
- Layer 6: expanded (vault → vault + instinct-based learning)
- Layer 7: NEW — context engineering as a first-class discipline
- Layer 8: NEW — intra-session state management

**Core design principle (from pi.dev):**
Minimal core, maximal extensibility. The superharness identity core should be ~30 lines.
Everything else is discoverable, not preloaded.

---

## Open Questions for Iteration 3

1. Should Layer 7 (Context) be a standalone layer or a cross-cutting concern that applies to all layers?
2. How aggressive should the hub-document refactor be? Rewrite agent-context.md now or wait?
3. Is the instinct protocol too ambitious for v0.3? Should it be v0.4?
4. Should the routing layer include actual agent-mux JSON contracts or stay conceptual?
5. What's the right format for progress files? Anthropic uses .txt, community uses .md/.yaml.
6. How much of pi.dev's "minimal core" philosophy should superharness adopt? Is 30 lines realistic?
7. Should session tree branching be a protocol or left to the tools (Claude Code already has /tree-like features)?
