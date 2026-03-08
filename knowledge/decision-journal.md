# Decision Journal — Layer 6

The code shows WHAT was built. The git log shows WHEN. Nothing shows WHY. The decision journal fills that gap.

---

## Why This Exists

Six months from now you'll look at code and ask "why did we choose X over Y?" The answer is in a conversation that no longer exists, in a session that was compacted, in your head where it's already faded.

The decision journal captures WHY during the work — not at the end when you've forgotten the reasoning, but in the moment when the trade-off is fresh.

---

## Where Decisions Live

### 1. In contracts (feature-specific)
The `decisions:` section of `.superharness/contract.yaml` captures choices made during a feature. Stays with the contract.

### 2. In the ledger (chronological)
Every decision gets a one-line entry in `.superharness/ledger.md`:
```
### 22:00 — claude-code — Planning
- Decision: JWT over session tokens (stateless, microservices-ready)
```

### 3. In the vault (permanent, cross-project)
Significant architectural decisions get deposited via /upvault as ADRs (Architecture Decision Records):
```markdown
---
date: 2026-03-08
tags:
  - decision
  - architecture
  - [technology]
project: [project-name]
---

# ADR: [Decision Title]

## Status
Accepted | Superseded by [link] | Deprecated

## Context
[What situation required a decision?]

## Options Considered
1. [Option A] — [pro/con]
2. [Option B] — [pro/con]

## Decision
[What was chosen and WHY]

## Consequences
[What this means going forward — trade-offs accepted]
```

---

## Agent Instruction

Every agent operating under superharness should auto-log decisions:

> When you make a choice between alternatives (library A vs B, approach X vs Y, architecture pattern, tool selection), log it in the active contract's `decisions:` section AND append a one-liner to the ledger. Format: what was chosen, what was rejected, why. Do this DURING the work, not at session end.

This instruction goes in CLAUDE.md and AGENTS.md for every project using superharness.

---

## Decision Categories

| Category | Example | Where to Log |
|----------|---------|-------------|
| **Library choice** | "chose jsonwebtoken over passport.js" | Contract + ledger |
| **Architecture** | "chose microservices over monolith" | Contract + vault (ADR) |
| **Pattern** | "chose composition over inheritance" | Contract + ledger |
| **Tool** | "chose Codex for this task, not Claude" | Ledger only |
| **Scope** | "deferred rate limiting to next sprint" | Contract (do_not section) |
| **Recovery** | "reverted to approach A after B failed" | Contract (failures + decisions) |

---

## Rules

1. **Log during the work, not after.** Post-session journaling misses half the decisions.
2. **Include what was rejected.** "Chose A" is incomplete. "Chose A over B because [reason]" is useful.
3. **Big decisions go to the vault.** If it affects architecture or would apply to other projects, /upvault as ADR.
4. **Small decisions stay in the contract.** Library choices, pattern choices, scope decisions — contract-level.
5. **Review decisions monthly.** During vault maintenance (weekend block): are past decisions still valid?
