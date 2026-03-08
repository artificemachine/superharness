# Failure Memory

Every framework tracks what to do. None track what NOT to do. Knowing what failed and why is as valuable as knowing what works.

---

## Where Failures Live (3 tiers)

### Tier 1: Contract (project-specific, short-lived)
The `failures:` section of `.superreins/contract.yaml`. Captures what didn't work during a feature. Any agent can read it, any agent can write to it.

```yaml
failures:
  - what: "Tried passport.js for auth"
    why_failed: "12 dependencies, 3 config files for a simple JWT check"
    date: 2026-03-08
    by: codex-cli
    alternative: "Raw jsonwebtoken — 1 dependency, 20 lines"
```

### Tier 2: Cross-agent store (project-level, persistent)
File: `.superreins/failures.yaml` — survives across contracts. Both Claude Code and Codex CLI read this before starting work.

```yaml
# .superreins/failures.yaml
- what: "SQLite for concurrent writes"
  why_failed: "Write locks under load, 500ms+ latency with 5 concurrent users"
  date: 2026-02-15
  by: claude-code
  alternative: "PostgreSQL with connection pooling"
  applies_to: "any database choice in this project"

- what: "Inheritance for middleware chain"
  why_failed: "Deep hierarchy, hard to test individual middleware"
  date: 2026-02-20
  by: codex-cli
  alternative: "Composition with pipe() pattern"
  applies_to: "middleware architecture"
```

**Why this tier exists:** Claude Code's native Auto Memory and Session Memory only work for Claude Code. Codex CLI can't read them. `.superreins/failures.yaml` is a plain file both agents access.

### Tier 3: Vault (global, permanent, cross-project)
For failures that apply everywhere — deposited via /upvault with tag `failure-memory`. Claude Code can search these via Obsidian MCP. Codex gets them through AGENTS.md "Do Not" rules.

### Promotion rules
- Failure appears in 1 contract → stays in contract
- Same failure in 2+ contracts → promote to `.superreins/failures.yaml`
- Failure applies across projects → promote to vault + add to AGENTS.md "Do Not"

---

## Integration with Claude Code Native Memory

Claude Code now has Auto Memory (automatic) and Session Memory (conversation summaries). These capture failures within Claude sessions automatically. superreins does NOT duplicate this.

**What Claude Code handles:** failures within a single Claude Code session chain.
**What superreins handles:** failures that need to cross to Codex CLI, Ollama, or future agents.

Rule: if a failure only matters for Claude Code → let Auto Memory handle it. If it matters for ANY other agent → write it to `.superreins/failures.yaml`.

---

## Auto-Search Protocol

Before implementing any non-trivial approach:

1. Read `.superreins/failures.yaml` (cross-agent store)
2. Read current contract's `failures:` section
3. Read CLAUDE.md / AGENTS.md "Do Not" sections
4. (Claude Code only) Check vault for `failure-memory` + technology name
5. If a match → report it before proceeding:
   "This approach was tried on [date] and failed because [reason]. Alternative was [X]. Continue anyway?"

---

## Failure Format

```yaml
what: "Brief description of what was attempted"
why_failed: "Specific, technical reason — not vague"
date: "2026-03-08"
by: "claude-code | codex-cli | ollama | human"
alternative: "What worked instead (if known)"
applies_to: "When would someone hit this again?"
```

---

## Rules

1. **Log failures immediately.** Not at session end. During the work.
2. **Be specific.** "Didn't work" is useless. "passport.js adds 12 dependencies for a simple JWT check" is useful.
3. **Include the alternative.** A failure without an alternative just says "don't." An alternative says "do THIS instead."
4. **Promote repeating failures.** 2+ contracts → project store. Cross-project → vault.
5. **Search before implementing.** 10 seconds of search saves 30 minutes of re-discovery.
6. **Don't duplicate Claude Code's memory.** If it only matters for Claude → let Auto Memory handle it.
