# Session Discipline — Layer 4

Session management that prevents the anti-patterns you know you have.

---

## Session Types

### Evening Session (1-2 hrs)

```
1. goclaude → clean context, enter project
2. /remember → reload CLAUDE.md + Serena memory + vault search
3. Read state/tasks.md → pick ONE task (planned last session)
4. Route task → interactive (Claude Code) or batch (Codex)
5. Execute until task is done or time is up
6. Write state/progress.md → checkpoint before stopping
7. /upvault → deposit learnings to vault
8. If ready: /ship → security + test + review + commit
9. Plan tomorrow → update state/tasks.md with next task
```

**The rules:**
- ONE task per evening. No context-switching. No "quick side thing."
- Planning happens at the END, not the start. You sit down to execute, not to think.
- If the task isn't finished, checkpoint state and continue tomorrow. Don't rush.
- If you're tired, /upvault and stop. Tired coding = negative progress.

### Weekend Block (5-10 hrs)

```
1. Review vault: what shipped this week? What's next?
2. Plan 1-2 substantial tasks for the block
3. goclaude → enter project with clean context
4. /remember → full context reload
5. Execute task 1 (deep work, 2-4 hrs)
6. Cross-agent review pass (different agent reviews the work)
7. /ship → deploy task 1
8. Break. Walk. Don't code for 15 min.
9. Execute task 2 if energy allows
10. Vault maintenance: update MOCs, connect notes, clean inbox
11. Plan next week's evening tasks → write to state/tasks.md
```

**The rules:**
- Max 2 substantial tasks per weekend block.
- Cross-agent review is mandatory before shipping.
- Take a real break between tasks. Context-switching without a break = worse code.
- Vault maintenance is a task, not an afterthought. Budget 30-60 min.

---

## Session Bookends

Every session, regardless of type:

| Phase | Action | Time |
|-------|--------|------|
| **Start** | /remember → read state files → pick task | 5 min |
| **Work** | Execute task with checkpointing | 80% of session |
| **End** | /upvault → update state/tasks.md → plan next | 10 min |

The bookends are non-negotiable. Skipping /remember = re-explaining context. Skipping /upvault = losing compound value. Skipping planning = wasting tomorrow's start time.

---

## Anti-Pattern Guards

### Scope Creep (your #1 anti-pattern)
- state/tasks.md has an "Out of Scope" section. Use it.
- If a new idea appears mid-task: write it to vault inbox, NOT state/tasks.md
- The rule: "Is this the task I sat down to do?" If no, it waits.

### Over-Planning as Procrastination (#2)
- Planning is max 10 min at session END, not 30 min at session START
- If you're still "planning" after 10 min, you're avoiding the work
- The fix: start with the smallest possible first step. Momentum follows.

### Shiny Object (#3)
- New tool? New framework? Write a vault note. Don't install it today.
- Evaluate new tools during vault maintenance (weekend block), not during work time.
- The question: "Does this tool solve a problem I hit THIS WEEK?" If no, defer.

---

## Session Recovery

When starting a session and you don't know where you left off:

1. Read `state/progress.md` → most recent checkpoint
2. Read `state/tasks.md` → what's remaining
3. Read `state/plan.md` → the approach and decisions
4. If state files don't exist → read CHANGELOG.md → search vault for session logs
5. If still lost → start with /remember and describe the project to the agent

---

## Rules

1. **One task per evening.** The constraint is the feature.
2. **Plan at the END, not the start.** Execute when you sit down.
3. **Bookends are mandatory.** /remember, /upvault, state update. Every session.
4. **New ideas go to vault inbox.** Not to the current task.
5. **Break between tasks.** 15 min minimum during weekend blocks.
6. **Tired = stop.** /upvault and close. Tomorrow-you has more context than tired-you.
