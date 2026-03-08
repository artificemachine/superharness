# Failure Memory — Layer 6

Every framework tracks what to do. None track what NOT to do. Knowing what failed and why is as valuable as knowing what works.

---

## Why This Exists

Without failure memory, agents re-attempt approaches that already failed:
- "Let me try passport.js for auth" — you tried it last month, too heavy
- "Let me use SQLite for this" — you discovered it doesn't handle concurrent writes
- "Let me refactor with inheritance" — you learned composition was better for this codebase

Each re-attempt costs tokens, time, and momentum. Failure memory prevents the loop.

---

## Where Failures Live

### 1. In contracts (project-specific)
The `failures:` section of `.superharness/contract.yaml` captures approach failures within a specific feature. These are short-lived — relevant during the feature, archived after.

### 2. In the vault (permanent, cross-project)
Failures that apply broadly get deposited via /upvault:
```markdown
---
date: 2026-03-08
tags:
  - failure-memory
  - [technology]
project: [project-name]
---

# Failed: [approach name]

## What was tried
[1-2 sentences]

## Why it failed
[specific reason, not vague]

## What worked instead
[the actual solution, if found]

## Applies to
[when would someone hit this again?]
```

### 3. In CLAUDE.md / AGENTS.md (per-project guardrails)
Persistent failures become rules:
```markdown
## Do Not
- Do not use passport.js in this project (over-engineered, see vault note)
- Do not use synchronous file reads in the API layer (blocks event loop)
```

---

## Failure Format

```yaml
what: "Brief description of what was attempted"
why_failed: "Specific, technical reason it didn't work"
when: "2026-03-08"
where: "project-name or general"
who: "claude-code | codex-cli | human"
alternative: "What worked instead (if known)"
severity: "wasted 5 min | wasted 1 hr | caused a bug | broke prod"
```

---

## Auto-Search Protocol

Before implementing any non-trivial approach:

1. Search vault for `failure-memory` + `[technology/pattern name]`
2. Check current project's `.superharness/contract.yaml` failures section
3. Check CLAUDE.md / AGENTS.md "Do Not" sections
4. If a previous failure matches → report it before proceeding
   - "This approach was tried on [date] and failed because [reason]. Alternative was [X]. Continue anyway?"

---

## Rules

1. **Log failures immediately.** Not at session end. During the work, when the failure is fresh.
2. **Be specific.** "Didn't work" is useless. "passport.js adds 12 dependencies and requires 3 config files for a simple JWT check" is useful.
3. **Include the alternative.** A failure without an alternative just says "don't do this." An alternative says "do THIS instead."
4. **Promote repeating failures.** If the same failure appears in 2+ contracts, it becomes a CLAUDE.md rule.
5. **Search before implementing.** The 10 seconds of search saves the 30 minutes of re-discovering the failure.
