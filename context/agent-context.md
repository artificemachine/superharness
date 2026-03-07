# Developer Context — Maxime Roy

> Embed this file into your global CLAUDE.md (Claude config directory) and adapt for your global AGENTS.md (Codex config directory).
> Everything below is written for the agent to read, not the human.

---

## Who

Maxime Roy. C++/Python/Rust/Solidity developer. 15+ years. Montreal.
Contract: Zimmer Biomet (C++/Qt/QML, medical devices).
Main company: new.blacc (all ventures consolidated under this entity).
Side: Cypher Farms (Proxmox infrastructure R&D, partnership — separate from new.blacc).
Domain expertise: ~7,000 hrs crypto/DeFi/macro/TradingView/TFSA-ETF. Solidity + Rust learned for Web3 career path.

## How I Work

- Unix philosophy: composable primitives over frameworks
- Automation-first: aliases, scripts, automation loops
- Documentation-as-code: this file IS the project memory
- Testing required: Catch2/GTest for C++, pytest for Python
- Git discipline: pre-commit hooks, security scan before ship
- Obsidian vault: second brain, updated every session via /upvault

## Tech Stack

- Languages: C++ (11-20), Python (3.10-3.14), Bash, Rust, JS/TS, Go, Solidity
- Frameworks: Qt/QML, Docker, Terraform, Ansible
- AI tools: Claude Code, Codex CLI, Serena, Context7, Memory Bank, CCFlare
- Infra: M2 Max, Proxmox cluster (co-operated with a friend via Cypher Farms — GPU nodes), WireGuard, Ollama, N8N

## Preferences

- Keep harness simple. Strip tools down to primitives.
- Use file system as external memory (progress files, plans, checklists)
- Sub-agents for isolated tasks, return summaries only
- Run /remember at session start, /upvault at session end
- Never skip security scan in /ship pipeline

## Protected Files

- CLAUDE.md — do not edit unless explicitly asked
- .env, credentials, tokens — never read, never commit

---

## AI Tooling Stack

| Tool | Role |
|------|------|
| Claude Code | Primary interactive agent. Sub-agents, MCP servers, slash commands (/ship, /remember, /simplify, /super_reviewer, /upvault) |
| Codex CLI | Parallel agent for sandboxed batch work. Skills system. AGENTS.md-driven |
| Serena | Semantic code search via MCP. Reduces token waste on large codebases |
| Context7 | Live documentation lookup. Prevents outdated API usage |
| Memory Bank | Persistent cross-session facts via MCP |
| Better-CCFlare | API proxy + cost tracking dashboard (localhost:8080) |
| Cowork | File/task automation, Obsidian integration, browser agent |

## Cross-Agent Setup

Both Claude Code and Codex CLI can share the same repo:
- Model-agnostic sections (build, test, conventions) → identical in CLAUDE.md and AGENTS.md
- Claude-specific sections (MCP, model selection) → CLAUDE.md only
- Codex-specific sections (skills, repo-guardrails) → AGENTS.md only
- Ship pipeline: security → rules verify → branch → hooks → test → build → hygiene → commit

---

## Task Routing

Use this table to decide execution mode before starting any task:

| Task Type | Agent | Mode | Why |
|-----------|-------|------|-----|
| Interactive exploration, debugging, refactoring | Claude Code | Interactive session | Needs environment access, MCP, real-time feedback |
| Parallel batch work (multiple independent files) | Codex CLI | `codex --approval=auto-edit` | Sandboxed, safe for bulk generation |
| Code review of AI output | Cross-agent | Claude reviews Codex output (or reverse) | Different model catches different bugs |
| Documentation, vault notes, learning synthesis | Cowork | Desktop session | Obsidian MCP, browser agent, file management |
| Quick one-off questions, API lookups | Claude Code | Single prompt | Don't spin up a loop for a 30-second answer |

---

## Workflow — Session Templates

### Evening Session (~1–2 hrs)

```
1. goclaude → clean context, enter project
2. /remember → reload CLAUDE.md + Serena memory
3. Identify next task
4. Route task (interactive / Codex)
5. Execute until task is done or time is up
6. /upvault → save session learnings to Obsidian
7. If ready: /ship → security + test + commit
```

### Weekend Block (~5–10 hrs)

```
1. Review vault: what shipped this week? What's next?
2. Plan weekend tasks
3. devloop → CCFlare for autonomous work
4. Cross-agent review pass
5. /ship → deploy
6. Vault maintenance: update MOCs, connect notes
7. Plan next week's evening tasks
```

---

## Multiplier Principles

1. **Context pre-loading.** Every project has CLAUDE.md and AGENTS.md. The AI starts at 80% context. Never explain the project twice.
2. **Session plan before you sit down.** The plan exists before you start. Execute, don't plan. Planning happens at the end of the previous session.
3. **Cross-agent review.** Don't review your own AI's code. Let the other agent review it.
4. **Vault as compound interest.** /upvault deposits knowledge. /remember withdraws it. The vault gets richer over time.
5. **Alias everything.** Zero friction: `devloop`, `goclaude`, `claudecost`. Every repeated action has a shortcut.
6. **Progressive skill building.** /commit → /ship → cross-agent pipeline. Each layer compounds.

## Anti-Patterns — Do Not

- Chase new models. The harness matters more. A better model + your harness = automatic upgrade.
- Build custom tools when bash primitives work. Vercel experiment: stripped-down → 100% accuracy, 40% fewer tokens.
- Manually review what an agent can review. Use cross-agent review.
- Context-switch between projects in a single evening session. One task, one ship.
- Skip the vault deposit. 2 minutes of /upvault saves 20 minutes next session.

---

## Next Builds

1. **`/route` slash command** — takes a task description, recommends Claude Code / Codex based on routing table.
2. **Session task template** — pre-structured phases so you just fill in tasks.
3. **Cross-agent review workflow** — standard post-implementation step where one agent reviews the other's output.
4. **Session summary auto-export** — /upvault captures learnings + routes them to the correct vault MOC.

---

*Update this file monthly or when your stack changes. This is the single source of truth for how every AI session should behave.*
