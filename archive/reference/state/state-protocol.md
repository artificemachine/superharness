# State Protocol — Layer 8

How sessions survive across compaction, across agents, and across days.

---

## The Problem

Claude Code's context window is ~200K tokens. When it fills, compaction summarizes older messages — lossy compression that drops nuance, reasoning, and the "why" behind decisions. Long sessions degrade. Agent handoffs lose context. Session boundaries break continuity.

superharness Layer 6 (Knowledge) handles cross-session learning via the vault.
Layer 8 (State) handles **intra-session survival** — keeping the agent effective even when compaction hits.

---

## The Progress File Triplet

Three files maintained during any non-trivial session:

### 1. `state/plan.md` — What We're Building
```markdown
# Current Plan
## Goal
[One sentence: what we're trying to achieve]
## Approach
[2-3 sentences: how we're doing it and why this approach]
## Decisions Made
- [Decision 1]: [chosen option] because [reason]
- [Decision 2]: [chosen option] because [reason]
## Open Questions
- [Question that still needs answering]
```

### 2. `state/progress.md` — Where We Are Right Now
```markdown
# Progress
## Last Completed
[What was just finished, with enough detail to continue]
## Current Step
[What's in progress right now]
## Files Modified
- [path]: [what changed and why]
## Blockers
- [Anything preventing forward progress]
```

### 3. `state/tasks.md` — What's Left
```markdown
# Remaining Tasks
- [ ] [Task 1 — specific, actionable]
- [ ] [Task 2]
- [x] [Task 3 — completed]
## Out of Scope (do not start)
- [Thing that's tempting but not this session's job]
```

---

## When to Write State

| Trigger | Action |
|---------|--------|
| Starting a non-trivial task | Write plan.md + tasks.md |
| Completing a major step | Update progress.md + check off tasks.md |
| Before deep work (>30 min estimated) | Checkpoint all three files |
| After a significant decision | Add to plan.md decisions section |
| Context window >50% (if you can estimate) | Checkpoint all three files |
| Before ending session | Update all three + /upvault |
| After compaction hits | Read all three files, then continue |

---

## Handoff Format

When transitioning between sessions or agents, write a structured handoff:

```yaml
# Session Handoff
date: YYYY-MM-DD
agent: [Claude Code | Codex CLI | Cowork]
session_type: [evening | weekend | continued]

## Context
project: [project name]
branch: [git branch]
goal: [one-line goal]

## Accomplished
- [what was done]

## State
current_step: [where we stopped]
files_modified:
  - path: [file]
    change: [what and why]
blockers:
  - [if any]

## Next
- [immediate next step]
- [step after that]

## Decisions
- [decision]: [chosen] because [reason]

## Do Not
- [anti-pattern specific to this task]
```

---

## Session Tree Awareness

Sessions aren't always linear. You might:
- Try approach A, realize it's wrong, branch back to try approach B
- Run a sub-agent that explores while you continue on the main path
- Hand off to Codex for implementation while Claude Code reviews

The state protocol accounts for this by treating state files as **checkpoints**, not a journal. Each checkpoint is a snapshot you can return to. Write a new checkpoint before branching. Name branches in progress.md.

---

## Recovery Protocol

When an agent seems confused (post-compaction, post-handoff, or new session):

1. "Read state/progress.md, state/plan.md, and state/tasks.md"
2. "Continue from where we left off"
3. If files don't exist: "Read CHANGELOG.md for full project context"
4. If still confused: "Search the vault for [project name] session logs"

---

## Rules

1. **State files live in the project, not the harness.** Each project gets its own `state/` directory (or `.state/` if you prefer hidden).
2. **State files are ephemeral.** They describe the current session's work. They're not documentation. Delete or archive after shipping.
3. **The vault is permanent, state is temporary.** /upvault captures learnings. State files capture work-in-progress.
4. **Don't over-write state.** Three files, each under 30 lines. If state files get long, you're doing too much in one session.
5. **Compaction is not failure.** It's expected. The protocol exists so compaction doesn't lose your work.
