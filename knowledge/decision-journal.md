# Decision Journal

The code shows WHAT was built. The git log shows WHEN. Nothing shows WHY. The decision journal fills that gap.

---

## Where Decisions Live (3 tiers)

### Tier 1: Contract (feature-specific, short-lived)
The `decisions:` section of `.superreins/contract.yaml`. Captured during the work by whichever agent makes the choice.

```yaml
decisions:
  - what: "JWT over session tokens"
    why: "Stateless, works with microservices, Codex has strong JWT patterns"
    rejected: "Session tokens — stateful, requires Redis for multi-server"
    date: 2026-03-08
    by: claude-code
```

### Tier 2: Cross-agent ADR store (project-level, persistent)
File: `.superreins/decisions.yaml` — architectural decisions that outlive any single contract. Both Claude Code and Codex CLI read this.

```yaml
# .superreins/decisions.yaml
- id: adr-001
  title: "PostgreSQL over SQLite"
  status: accepted  # accepted | superseded | deprecated
  context: "Need concurrent write support for API layer"
  decision: "PostgreSQL with connection pooling via pg-pool"
  rejected: "SQLite (write locks under load), MongoDB (overkill for relational data)"
  consequences: "Requires PostgreSQL in Docker for local dev"
  date: 2026-02-15
  by: claude-code

- id: adr-002
  title: "Composition over inheritance for middleware"
  status: accepted
  context: "Middleware chain was getting deep and hard to test"
  decision: "pipe() pattern with pure functions"
  rejected: "Class hierarchy (hard to test individual middleware, deep coupling)"
  consequences: "Each middleware is independently testable but requires explicit wiring"
  date: 2026-02-20
  by: codex-cli
```

**Why this tier exists:** Claude Code's Auto Memory captures decisions automatically for Claude sessions. But Codex CLI can't read Claude's memory. `.superreins/decisions.yaml` is the shared store both agents access.

### Tier 3: Vault (global, permanent, cross-project)
Decisions that apply everywhere — deposited via /upvault with tag `decision`. Full ADR format in the Obsidian vault.

### Promotion rules
- Feature-specific decision → stays in contract
- Affects project architecture → promote to `.superreins/decisions.yaml`
- Applies across projects → promote to vault as full ADR

---

## Integration with Claude Code Native Memory

Claude Code's Auto Memory already captures decisions within Claude sessions. superreins does NOT duplicate this.

**What Claude Code handles:** decisions within a single Claude session chain.
**What superreins handles:** decisions that need to cross to Codex CLI, Ollama, or future agents.

Rule: if a decision only matters for Claude Code → let Auto Memory handle it. If Codex or another agent needs to know → write it to `.superreins/decisions.yaml`.

---

## Integration with Archgate (optional)

Archgate CLI can enforce decisions as pre-commit rules and CI checks. If installed:
- Decisions in `.superreins/decisions.yaml` can feed Archgate rules
- Pre-commit hooks validate code against architectural decisions
- CI pipeline checks for decision violations

This turns documentation into enforcement. Optional but recommended for critical projects.

---

## Agent Instruction

Every agent operating under superreins should auto-log decisions:

> When you make a choice between alternatives (library A vs B, approach X vs Y, architecture pattern, tool selection), log it in the active contract's `decisions:` section AND append a one-liner to the ledger. Include what was chosen, what was rejected, and why. Do this DURING the work, not at session end.

---

## Rules

1. **Log during the work, not after.** Post-session journaling misses half the decisions.
2. **Include what was rejected.** "Chose A" is incomplete. "Chose A over B because [reason]" is useful.
3. **Big decisions go to the project store.** Architecture or pattern decisions → `.superreins/decisions.yaml`.
4. **Small decisions stay in the contract.** Library choices, scope decisions — contract-level.
5. **Don't duplicate Claude Code's memory.** If it only matters for Claude → let Auto Memory handle it.
6. **Enforce what matters.** Use Archgate or pre-commit hooks for critical decisions. Documentation alone has no teeth.
