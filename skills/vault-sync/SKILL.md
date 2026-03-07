---
name: vault-sync
description: Sync session learnings to Obsidian vault and reload context from vault
triggers:
  - vault
  - obsidian
  - save learnings
  - session end
  - "/upvault"
  - "/remember"
---

# Vault Sync

The Obsidian vault is compound interest. Every session deposits knowledge. Future sessions withdraw it.

## /remember — Start of Session

Reload context from vault and project memory:

1. **Read CLAUDE.md** — Project-specific context
2. **Read Serena memories** — Cross-session facts stored via MCP
3. **Search vault** — Find related notes for current task
4. **Report findings** — "Found: [note names] — [brief relevance]" or "No relevant context found"

### Implementation
```
1. Check for CLAUDE.md in project root, then the global CLAUDE.md in your Claude config directory
2. If Serena MCP is available: list_memories → read relevant ones
3. Search Obsidian vault for task-related keywords
4. Summarize what was found (2-3 lines max)
```

## /upvault — End of Session

Deposit session learnings into the vault:

1. **What was accomplished** — Tasks completed, decisions made
2. **What was learned** — New patterns, gotchas, configurations discovered
3. **What's next** — Unfinished work, next steps, blockers

### Note Format
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

### Vault Location Rules
- Session logs → `notes/1_ai/session-logs/`
- Technical notes → `notes/1_ai/[tool-name]/`
- Project-specific → `notes/[project-category]/[project-name]/`
- Infrastructure → `notes/1_infrastructure/`

## Rules

- Run /remember at session start. Every time.
- Run /upvault at session end. Even if the session was short.
- 2 minutes of /upvault saves 20 minutes next session.
- Skip notes marked with `#WIP` tag in frontmatter.
- Keep session logs concise — bullet points, not prose.
- Link to related vault notes using `[[wikilinks]]` when possible.
