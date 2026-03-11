# Vault Protocol — Layer 6

The Obsidian vault is compound interest. Every session deposits knowledge. Future sessions withdraw it. The vault gets richer over time — but only if you deposit AND withdraw consistently.

---

## The Three Operations

### /remember — Session Start (Withdrawal)

Reload context from vault and project memory:

1. Read CLAUDE.md in project root (project-specific context)
2. Read global CLAUDE.md (identity, cost guards, model selection)
3. If Serena MCP available: `list_memories` → read relevant ones
4. Search Obsidian vault for task-related keywords
5. Report: "Found: [note names] — [brief relevance]" or "No relevant context found"

**Implementation:**
```
1. Check for CLAUDE.md in project root, then global CLAUDE.md
2. If Serena MCP available: list_memories → read relevant ones
3. Search Obsidian vault for task-related keywords
4. Summarize findings (2-3 lines max — context budget matters)
```

### /upvault — Session End (Deposit)

Deposit session learnings into the vault:

1. What was accomplished — tasks completed, decisions made
2. What was learned — new patterns, gotchas, configs discovered
3. What's next — unfinished work, next steps, blockers

**Note format:**
```markdown
---
date: YYYY-MM-DD
tags:
  - session-log
  - [project-tag]
project: [project-name]
---

# Session: [Date] — [Project]

## Accomplished
- [task 1]
- [task 2]

## Learned
- [insight 1]
- [insight 2]

## Next
- [next step 1]
- [blocker if any]
```

**Vault location rules:**
- Session logs → `notes/1_ai/session-logs/`
- Technical notes → `notes/1_ai/[tool-name]/`
- Project-specific → `notes/[project-category]/[project-name]/`
- Infrastructure → `notes/1_infrastructure/`

### Mid-Session Retrieval — During Work (Active Withdrawal)

This is what was missing from v0.2. The vault isn't just for bookends — it's an active resource during work.

**Auto-search triggers:**

| Trigger | Search For | Why |
|---------|-----------|-----|
| Before implementing a pattern | "[pattern name]" in vault | May have solved this before or documented gotchas |
| Before choosing a library/tool | "[library name]" in vault | May have evaluated it before |
| When hitting an error | "[error message]" in vault | May have debugged this before |
| Before architectural decisions | "[module/component name]" in vault | May have documented design reasoning |
| When starting work on a project | "[project name]" in vault | Recover context from previous sessions |
| Before writing a CLAUDE.md section | "CLAUDE.md" + "[topic]" in vault | Reuse patterns from other projects |

**Implementation:**
When using Claude Code or Cowork with Obsidian MCP:
```
obsidian_simple_search("[relevant keyword]")
→ If results found: read the most relevant note
→ Extract applicable insight (2-3 lines)
→ Inject into current context
→ Continue with task
```

**Rule:** Mid-session searches should be SELECTIVE. Don't search for everything. Search when you're about to make a decision or implement something non-trivial.

---

## Instinct Protocol (Future — Layer 6 Extension)

Beyond manual deposits, the harness should auto-detect patterns:

### Concept
An "instinct" is a pattern the harness learns from repeated behavior:
- "You always run tests before committing in this project" → auto-suggest test run if skipped
- "You prefer composition over inheritance" → flag inheritance patterns for review
- "You always forget to update docs after API changes" → remind when API files change

### Implementation Path
1. **v0.3 (now):** Manual — document known patterns in CLAUDE.md per project
2. **v0.4 (near-term):** Semi-auto — agent suggests patterns it notices, you confirm
3. **v0.5 (future):** Auto — instinct log grows, exports/imports between projects

### Instinct Format (future)
```yaml
instinct: test-before-commit
confidence: 0.9
source: observed 12/15 sessions
action: suggest running tests before /ship if not already run
project: [all | specific-project]
```

---

## Rules

1. **/remember at session start.** Every time. No exceptions.
2. **/upvault at session end.** Even short sessions. 2 minutes saves 20 next time.
3. **Search before implementing.** If the vault might have context, check first.
4. **Skip notes tagged `#WIP`** in frontmatter — they're incomplete.
5. **Keep session logs concise.** Bullet points, not prose. Link with `[[wikilinks]]`.
6. **Don't dump the vault into context.** Extract relevant lines only. Context budget matters.
