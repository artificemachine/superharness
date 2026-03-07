# superharness

## What Is This?

The system that sits between you and your AI agents.

Not a plugin. Not a collection of skills. Not a tool you install and forget. **superharness is your personal harness architecture** — the full operating environment that determines whether an AI model's intelligence actually translates into useful work for you, specifically.

The same Claude model scored **78%** inside one harness and **42%** inside another. Same brain, different body, nearly double the performance. That gap is entirely explained by everything the harness does: how it manages context, how it hands off state between sessions, how it connects tools, how it verifies results. The harness is not an optimization layer on top of a model. It's a performance multiplier.

You've already built this harness — organically, over months, across your Claude config, Codex config, DevOpsCelstn workspace, the Obsidian vault, and your own working patterns. superharness is the name, the structure, and the portability layer for what already exists.

---

## The Problem It Solves

Your harness is currently scattered:

| Piece | Where It Lives Now | What It Does |
|-------|-------------------|-------------|
| Global rules | `CLAUDE.md` (global, in Claude config dir) | Model selection decision tree, cost guards, safety rules |
| Project rules | `CLAUDE.md` per repo | Build commands, conventions, protected files |
| Codex parity | `AGENTS.md` (global + per repo) | Same rules, Codex-native format |
| Slash commands | Claude commands directory (`commands/*.md`) | /ship, /remember, /upvault, /simplify, /super_reviewer |
| Codex skills | Codex skills directory (`skills/*/SKILL.md`) | ship, remember, upvault, simplify, super-reviewer |
| Session launcher | `goclaude` alias in `.zshrc` | `cd DevOpsCelstn && ./clean_context.sh && claude` |
| Shell environment | `.zshrc` + `.zsh_scripts/` | 100+ aliases, functions, path configs |
| Developer identity | Your head (partially in vault notes) | Who you are, what you know, your anti-patterns |
| Long-term knowledge | Obsidian vault (unsorted, raw ideas) | 7,000+ hours of accumulated insight |
| Routing decisions | Your head | Which agent gets which task, and why |
| Session discipline | Your head | How evening sessions and weekend blocks should run |

If you get a new machine, you clone dotfiles and re-install tools. But the *harness* — the system that makes your agents effective — has no single source of truth. It's not versionable. It's not portable. Pieces rot independently.

superharness fixes this.

---

## What superharness IS

**A personal harness architecture organized into six layers:**

### Layer 1: Identity — WHO you are
The most stable context across all projects. Changes slowly. Highest value per token.

- Developer profile: 15+ yrs C++/Python/Rust, 7,000 hrs crypto/DeFi/macro, Zimmer Biomet contract, new.blacc ventures
- Anti-patterns: scope creep, starting new projects before shipping, over-planning as procrastination
- Working constraints: solo dev, 10-20 hrs/week side projects, evening and weekend sessions

No other framework treats developer identity as a first-class component. superpowers doesn't know who you are. CLAUDE.md is project-specific. But the developer profile applies to EVERY project, EVERY agent, EVERY session.

### Layer 2: Agents — WHAT each agent needs
Cross-agent configuration that keeps Claude Code and Codex CLI in parity.

- Global CLAUDE.md → model selection rules, cost guards, safety rules
- Global AGENTS.md → same rules, Codex-native format
- Parallel commands/skills → /ship ↔ ship, /remember ↔ remember, /upvault ↔ upvault
- MCP servers (Claude Code only) → Serena, Context7, Obsidian

The key insight from your vault: these are complementary architectures, not competing tools. Claude Code = collaborator at your desk (MCP, sub-agents, environment access). Codex CLI = contractor in a clean room (sandboxed, repo-as-memory). superharness maintains both.

### Layer 3: Routing — WHERE tasks go
The dispatch logic that matches tasks to the right agent's architecture.

- Interactive exploration, debugging, refactoring → Claude Code
- Parallel batch work, independent file generation → Codex CLI
- Knowledge work, vault maintenance, research → Cowork
- Quick one-off questions → Claude Code interactive (not Codex)
- Model selection → Haiku for batch/simple, Sonnet default, Opus only after Sonnet fails 2×

This layer turns "which tool should I use?" from a gut feeling into a repeatable decision.

### Layer 4: Discipline — WHEN and HOW LONG
Session management that prevents the anti-patterns you know you have.

- Evening session (1-2 hrs): context load → one task → ship → /upvault
- Weekend block (5-10 hrs): review → plan 1-2 tasks → deep work → cross-agent review → ship → maintenance
- The rule: planning happens at the END of the previous session, not the start of this one
- The constraint: one task per evening. No context-switching. No starting project B.

### Layer 5: Quality — HOW GOOD
Verification gates that prevent shipping broken work.

- Security scan is always step 1 (reposec/grep for secrets). Non-negotiable.
- Cross-agent review before merge: Claude reviews Codex output, Codex reviews Claude output
- Never `--no-verify` on commits
- Never push directly to main/master
- Ship pipeline: security → rules verify → branch check → hooks → test → build → hygiene → commit

### Layer 6: Knowledge — WHY IT COMPOUNDS
The system that makes the harness smarter over time.

- /remember at session start → loads CLAUDE.md + Serena memory + vault search
- /upvault at session end → deposits learnings to Obsidian vault
- The vault is raw, unsorted, and that's OK — it's the deposit box. Curation is separate work.
- Every session that runs inside this harness adds value. Switching harnesses resets it to zero.

---

## What superharness IS NOT

- **Not a superpowers clone.** superpowers is a generic skills plugin anyone installs. superharness is your specific harness architecture.
- **Not a tool.** You don't "run" superharness. You work inside it. It's the environment, not the application.
- **Not finished.** The vault is raw ideas. The routing is partially in your head. The identity layer is being formalized for the first time. This is a living system.
- **Not a replacement for CLAUDE.md.** CLAUDE.md stays per-project. superharness is the system that generates and maintains those per-project files.

---

## Structure

```
superharness/
├── identity/                          ← Layer 1: WHO
│   ├── developer-profile.md           ← Skills, domains, gaps, anti-patterns
│   └── agent-context.md               ← How agents should work with you
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
│   ├── routing.md                     ← Task dispatch logic
│   ├── session-discipline.md          ← Evening and weekend templates
│   ├── ship-pipeline.md               ← Security-first quality gates
│   └── cross-agent-review.md          ← Review across agents
│
├── knowledge/                         ← Layer 6: WHY IT COMPOUNDS
│   ├── harness-thesis.md              ← The 78% vs 42% thesis
│   └── vault-protocol.md              ← /remember and /upvault patterns
│
├── templates/                         ← Bootstrap for new projects
│   ├── CLAUDE.md.template             ← Generate per-project CLAUDE.md
│   └── AGENTS.md.template             ← Generate per-project AGENTS.md
│
└── README.md                          ← This file
```

---

## The Compounding Thesis

Every session that runs inside this harness deposits value:
- CLAUDE.md files get refined → agents start smarter next session
- Vault gets a deposit → future sessions have more context to draw from
- Anti-patterns get documented → agents avoid your known failure modes
- Routing decisions get tested → you learn which agent fits which task
- Commands/skills get tuned → less friction, fewer explanations

Switching harnesses resets all of this to zero. That's the lock-in nobody prices in — and that's exactly why this framework is worth maintaining, versioning, and carrying across every project.

**superpowers teaches an agent how to work.**
**superharness teaches an agent how to work with you.**

---

## Current State

This is v0.1. The harness has been built organically over months. superharness is the first attempt to name it, structure it, and make it portable. Some layers are well-defined (agents, quality). Others are still in your head (routing, discipline) or raw in the vault (knowledge). That's fine. The framework exists to give those pieces a home as they mature.
