# Iteration 6 Research — 2026 Harness Engineering & Multi-Agent Patterns

Date: 2026-03-08

## Key Findings

### 1. Claude Code Native Memory (3-tier)
- Auto Memory: automatic, extracts architecture notes/debug insights/code style
- Session Memory: converts conversations to structured summaries at `$HOME/.claude/projects/<project>/memory/`
- CLAUDE.md: user-written project memory
- **Impact:** superharness should NOT duplicate what Claude Code handles natively. Focus on cross-agent memory.
- Source: code.claude.com/docs/en/memory

### 2. PreToolUse/PostToolUse Hooks
- Claude Code hooks go beyond SessionStart — PreToolUse can block/warn before actions
- Can enforce scope, security, branch protection at the tool level
- PostToolUse can auto-log changes
- **Impact:** Enforcement with teeth, not documentation
- Source: code.claude.com/docs/en/hooks

### 3. Specialized Review Agents
- Pattern: 9 parallel subagents each reviewing a different aspect
- Security, performance, style, architecture, tests, docs, dependencies, accessibility, API contracts
- Much deeper than "one reviewer checks everything"
- **Impact:** Added review-lenses.md with 7 lenses, assignable per-task

### 4. Archgate CLI — ADRs as Enforcement
- Turns Architecture Decision Records into CI/CD governance
- Runs in pre-commit hooks, feeds context to AI agents
- Decisions become enforceable rules, not just docs
- **Impact:** Optional integration for decision-journal.md
- Source: github.com/archgate/cli

### 5. Claude-Mem Plugin
- Auto-captures everything Claude does, compresses, re-injects in future sessions
- Solves cross-session memory problem for Claude Code
- But only for Claude Code — Codex still needs manual
- **Impact:** For Claude-only memory, consider Claude-Mem. For cross-agent, keep failures.yaml
- Source: github.com/thedotmack/claude-mem

### 6. Memory Engineering (4 types)
- Working memory, Procedural memory, Semantic memory, Episodic memory
- Most agents only have working memory
- Reflexion framework: converts failure signals to verbal feedback in episodic memory (+14% accuracy)
- Error propagation: corrupted memory poisons all downstream decisions
- **Impact:** failures.yaml is episodic memory. decisions.yaml is semantic memory. Both cross-agent.
- Sources: medium.com/@mjgmario (Memory Engineering), arionresearch.com (Error propagation)

### 7. Context Engineering 2026
- Now a systems engineering discipline, not just prompting
- 6 techniques: dynamic selection, compression, KV-cache optimization, selective injection, MCP standardization, context-as-systems
- KV-cache hit rate is the key production metric
- Manus (agent framework): "context is a first-class system with its own architecture"
- **Impact:** Claude Code handles this natively. Deprecated our context/ docs.
- Sources: pub.towardsai.net, manus.im/blog

### 8. Industry Standard Protocols
- Google A2A (Agent-to-Agent): Linux Foundation standard, "Agent Cards" for identity/capabilities
- OpenAI Agents SDK: native handoff support
- LangChain, AutoGen, Semantic Kernel: all have handoff patterns
- **Impact:** Our contract/handoff/ledger is simpler (file-based, no server). Keep it.

## What We Built Based on This

1. **PreToolUse hooks** — scope-guard.sh (blocks .env edits, warns on system files), branch-guard.sh (blocks push to main, warns on destructive git ops)
2. **PostToolUse hooks** — ledger-append.sh (auto-logs file changes to ledger)
3. **Review lenses** — 7 specialized review perspectives, assignable per-task in contract
4. **Cross-agent failure store** — .superharness/failures.yaml (both agents read/write)
5. **Cross-agent decision store** — .superharness/decisions.yaml (ADR-lite format)
6. **Deprecated** — context-engineering.md, anti-rot.md, session-discipline.md (replaced by hooks + native Claude Code features)
