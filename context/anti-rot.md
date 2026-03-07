# Anti-Rot Strategies — Layer 7

Context rot happens when the context window fills and compaction strips away nuance. The "why" disappears. Only a shallow "what" survives. This doc is the defense.

---

## Pre-Compaction Checkpoint

Before compaction hits (or before any block of deep work):

1. Write `state/progress.md` — where we are right now
2. Write `state/plan.md` — what we're building and why
3. Write `state/tasks.md` — what's left to do
4. These files survive compaction. After compaction: "Read state/ files and continue."

---

## Token Budget Discipline

**~200K token window. Budget it:**

| Component | Budget | Notes |
|-----------|--------|-------|
| System prompt + tool defs | ~15K | Automatic, can't control |
| CLAUDE.md / identity core | ~1-2K | Keep under 200 lines |
| Conversation history | ~80K | Compaction keeps this in check |
| Task work (the actual job) | ~100K | This is what matters |

**Rule of thumb:** If CLAUDE.md + rules take more than 10% of the window, they're too long.

---

## Cache-Friendly Patterns

Anthropic's prompt caching: identical prefixes get cached (cheaper, faster).

- **Keep CLAUDE.md stable** — don't rewrite it mid-session
- **Front-load stable context** — identity core first, volatile details last
- **System prompt consistency** — same project = same cache hit
- **Don't reorganize instructions mid-session** — invalidates cache

---

## Recovery After Compaction

When the agent seems confused or lost context:

```
1. "Read state/progress.md and state/tasks.md"
2. "Continue from where we left off"
3. If state files are stale: "Read CHANGELOG.md for project context"
4. If still lost: "Search vault for [project] session logs"
```

---

## Long Session Survival

For weekend blocks (5+ hours):

- Checkpoint every 30 minutes of heavy work
- After any major decision → write reasoning to state/plan.md
- After completing a subtask → update state/progress.md
- Before switching tasks → full checkpoint + clear notes on what's next
- If agent quality drops → new session with fresh context + state files
