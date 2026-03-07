---
name: evening-session
description: Template for 1-2 hour focused evening coding sessions
triggers:
  - evening session
  - short session
  - quick session
  - 1 hour
  - 2 hours
---

# Evening Session (~1-2 hrs)

Focused, single-task sessions. Execute, don't plan. The plan should exist before you sit down.

## Flow

### 1. Context Load (5 min)
```
goclaude → clean context, enter project
/remember → reload CLAUDE.md + Serena memory + vault search
```

### 2. Task Identification (5 min)
- Check session plan from previous session's /upvault
- If no plan exists: pick ONE task from project backlog
- Route the task (use session-routing skill)

### 3. Execute (45-90 min)
- One task. No context-switching.
- If blocked, document the blocker and move to a different subtask within the same project.
- If task completes early, do NOT start a new project. Use remaining time for:
  - Tests for what you just built
  - Documentation
  - Vault maintenance

### 4. Save (5 min)
```
/upvault → save session learnings to Obsidian
```

### 5. Ship (5 min, if ready)
```
/ship → security + test + commit
```
Only ship if the task is complete and passes all checks.

## Rules

- Session plan before you sit down. Planning happens at the end of the PREVIOUS session.
- One task, one ship. No multi-project evenings.
- If you didn't ship, that's fine. Document where you stopped.
- Always /upvault even if the session felt unproductive. The context is still valuable.

## Time Guardrails

| Phase | Max Time | If Over Budget |
|-------|----------|----------------|
| Context + routing | 10 min | Skip vault search, use CLAUDE.md only |
| Execution | 90 min | Stop. Save state. Ship or defer. |
| Save + ship | 10 min | Minimum: /upvault with 3 bullet points |
