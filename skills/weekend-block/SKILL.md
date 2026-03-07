---
name: weekend-block
description: Template for 5-10 hour deep work weekend sessions
triggers:
  - weekend session
  - long session
  - deep work
  - full day
  - 5 hours
  - 10 hours
---

# Weekend Block (~5-10 hrs)

Extended sessions for deep work, multi-step features, and infrastructure.

## Flow

### 1. Review (30 min)
- Review vault: what shipped this week?
- Read session logs from evening sessions
- Identify gaps, unfinished work, opportunities

### 2. Plan Weekend Tasks (30 min)
- Pick 1-2 major tasks (NOT 3+)
- Break each into subtasks with clear done-criteria
- Route each subtask (session-routing skill)
- Write the plan as a checklist in the project or vault

### 3. Deep Work Block (3-7 hrs)
- Execute plan sequentially
- Use cross-agent review after each major subtask
- Take breaks between subtasks (context compaction protection)
- If using autonomous loops: set clear guardrails and check-in points

### 4. Review Pass (30 min)
- Cross-agent review of all code written today
- Run full test suite
- Check for TODO/FIXME/HACK comments left behind

### 5. Ship / Deploy (30 min)
```
/ship → full pipeline (security → test → build → commit)
```
- If deploying: use the deploy checklist for the target (Docker, Proxmox LXC, etc.)

### 6. Maintenance (30 min)
- /upvault with comprehensive session log
- Update MOCs (Maps of Content) in vault
- Connect new notes to existing knowledge
- Plan next week's evening tasks

## Rules

- Max 2 major tasks per weekend block. Focus beats breadth.
- Cross-agent review after each major subtask, not just at the end.
- Breaks between subtasks are mandatory. Fresh context > stale context.
- Vault maintenance is NOT optional. This is where compound interest happens.
- Plan next week's evening sessions before closing. Future-you starts at 80% context.

## Checkpoint Template

After each subtask, log:
```
## Checkpoint: [subtask name]
- Status: DONE / PARTIAL / BLOCKED
- What shipped: [1-2 lines]
- Issues found: [or "none"]
- Next: [what follows]
```

## Time Budget

| Phase | Budget | Flex |
|-------|--------|------|
| Review + Plan | 1 hr | Fixed — don't skip |
| Deep work | 3-7 hrs | Adjust to energy |
| Review + Ship | 1 hr | Can extend for complex deploys |
| Maintenance | 30 min | Minimum 15 min even if tired |
