# Iteration 3b — Self-Critique and Original Thinking

**Date:** 2026-03-07
**Purpose:** Stop copying. Start thinking.

---

## What's Wrong With v0.3

### 1. It's a documentation project, not a system

Every file is a .md describing how things SHOULD work. None of it is executable. None of it enforces anything. If Maxime ignores session-discipline.md tomorrow, nothing happens. The harness has no teeth.

**The gap:** superharness describes a system. It doesn't implement one. A real harness would have hooks, scripts, automations, and enforcement — not just documents about good intentions.

**What would teeth look like:**
- A session-start hook that REFUSES to proceed without /remember
- A pre-commit hook that checks state/progress.md was updated
- A timer that triggers /upvault after 90 minutes of session
- A cost-tracking integration that blocks Opus if Sonnet wasn't tried first
- A routing script that takes a task description and returns a recommendation

### 2. It doesn't solve the REAL bottleneck

The harness thesis says the bottleneck is harness quality. But Maxime's actual bottleneck — documented in his own profile — is **shipping**. Zero shipped SaaS. Zero revenue. Five ventures, none generating income. Anti-pattern #1: scope creep.

A harness that makes AI sessions more efficient doesn't fix the shipping problem. A more efficient session that still doesn't ship is just a more efficient way to not ship.

**What would shipping-focused look like:**
- Layer 4 (Discipline) should have a SHIPPING GATE, not just session templates
- Every session's tasks.md should connect to a ship date
- The harness should track: weeks since last public ship. If >2 weeks, force a conversation about what's blocking.
- Anti-pattern detection should be ACTIVE, not just documented. "You've opened 3 new files in a project you weren't working on. This looks like scope creep. Continue?"

### 3. Eight layers is too many

The research said "minimal core." Then I built 8 layers with 15+ docs. That's not minimal. That's a bureaucracy.

A solo dev with 10-20 hrs/week doesn't need 8 layers of methodology. They need:
- WHO: identity core (30 lines) ✓ — this is good
- WHAT TO DO: one task, clear next step
- HOW TO NOT FAIL: the 3 things that actually derail you
- DID YOU SHIP: binary. yes/no.

Everything else is support documentation that gets loaded on demand. The 8-layer model is useful for UNDERSTANDING the system, but the OPERATING interface should be much simpler.

### 4. It doesn't account for motivation decay

Maxime works evenings and weekends. After a full day at Zimmer Biomet. The harness assumes a disciplined, motivated developer who follows protocols. But the real failure mode is: you're tired, you skip /remember, you noodle around for 45 minutes, you close the laptop having done nothing useful.

No framework in the research addresses this. They all assume the developer shows up ready to work. The real harness innovation would be designing for LOW-ENERGY states, not just optimal ones.

**What would energy-aware look like:**
- Session types based on energy, not just time: "high energy" (build features), "medium energy" (review/refactor), "low energy" (vault maintenance, docs, easy wins)
- A "5-minute start" protocol: the absolute minimum you can do in 5 minutes that still deposits value
- Pre-loaded session starters: "Here's what you were doing. Here's the smallest next step. Just do this one thing."

### 5. The vault protocol is backwards

/remember at start, /upvault at end. This assumes the developer remembers to do both. But the REAL compound value happens when the vault is woven INTO the work, not bolted on at the edges.

**What would vault-native look like:**
- Every decision the agent makes gets auto-logged (not just at session end)
- The agent auto-searches vault before implementing ANYTHING (not just when told to)
- Failed approaches get logged so future sessions don't re-attempt them
- The vault IS the harness memory, not a separate system you push/pull from

### 6. Cross-agent review is theater without metrics

"Use a different agent to review." OK. But how do you know the review caught anything? How do you know the review is worth the tokens? Without tracking review outcomes (bugs caught, bugs missed, false positives), cross-agent review is just a ritual.

**What would measured review look like:**
- Track: review found X issues, Y were real bugs, Z were false positives
- Over time: which agent is better at reviewing which type of code?
- Cost per bug caught: is cross-agent review worth it for this project?
- If the review consistently finds nothing: skip it (the code quality is already high enough)

### 7. No concept of "done"

superharness describes a perpetual improvement cycle. But when is a project DONE? When is a feature DONE? When do you stop iterating on the harness itself and start using it?

The risk: superharness becomes the ultimate scope-creep — infinitely iterable, never finished, a perfect expression of anti-pattern #2 (over-planning as procrastination).

**What would "done" look like:**
- superharness has a 1.0 definition: "the harness is 1.0 when [these specific things] work"
- Each project has a ship criteria in its CLAUDE.md
- The harness itself has a maintenance budget: max 1 hour/month on harness improvement
- After 1.0, changes are reactive (fix what breaks), not proactive (add what might be nice)

---

## Original Ideas — What No Framework Does

### Idea 1: Energy-Based Routing

Nobody routes tasks by developer energy level. They route by task type. But a tired developer doing architecture work produces worse output than a fresh developer doing grunt work with Haiku.

```
Energy: High   → Architecture, complex features, new projects
Energy: Medium → Implementation, debugging, refactoring
Energy: Low    → Vault maintenance, docs, code review, easy wins
Energy: Zero   → Don't code. Read vault notes. Plan tomorrow.
```

This would be the first harness that accounts for the human in the loop being a variable, not a constant.

### Idea 2: Ship Pressure

A counter that tracks days since last public ship. Visible at session start. Increases urgency as it grows. When it hits a threshold (e.g., 14 days), the harness actively pushes toward shipping:
- "You haven't shipped in 12 days. What's the smallest thing you can ship TODAY?"
- Blocks starting new features until something ships
- Suggests "ship-able slices" of current work

This directly attacks anti-pattern #1 (scope creep) with a structural mechanism, not willpower.

### Idea 3: Decision Journal (Auto-Logged)

Every significant decision made during a session gets logged automatically:
- "Chose library X over Y because Z"
- "Rejected approach A, went with B"
- "This error was caused by [root cause]"

Not at session end (you forget). During the work. The agent writes it as part of its normal output. Over time, this becomes the most valuable asset in the vault — a searchable history of WHY decisions were made.

### Idea 4: Failure Memory

When something fails (test, build, approach, library), log it with context. Future sessions search failure memory BEFORE attempting anything. "This approach was tried on [date] and failed because [reason]."

No framework tracks what DIDN'T work. They all track what to do. Knowing what NOT to do is equally valuable and prevents the "try the same wrong thing in a new session" loop.

### Idea 5: The 5-Minute Session

Design a session type that assumes you have exactly 5 minutes and zero motivation. What can you still accomplish?

- Read state/progress.md (30 seconds)
- Pick the single smallest task from tasks.md (30 seconds)
- Do that one thing (3 minutes)
- Update progress.md (30 seconds)
- /upvault one-liner (30 seconds)

If the harness makes the minimum useful session 5 minutes, you'll have far more sessions than if the minimum is 60 minutes. Volume beats intensity for compound value.

### Idea 6: Harness Scorecard

A monthly self-assessment:
- Sessions this month: X
- /remember compliance: Y%
- /upvault compliance: Z%
- Ships this month: N
- Days since last ship: D
- Vault deposits: V notes
- Anti-pattern triggers: which ones hit?

Quantify the harness. What gets measured gets managed. No other framework measures itself.

---

## What v0.4 Should Actually Be

Not more documentation. Implementation.

1. **Ship pressure counter** — a script that reads git log and reports days since last tagged release
2. **Energy-based routing** — add to routing.md, make it the PRIMARY routing axis
3. **5-minute session protocol** — a real, usable template
4. **Failure memory format** — add to vault protocol
5. **Decision journal** — agent instruction to auto-log decisions during work
6. **Define 1.0** — what does "done" look like for superharness itself?
7. **One executable hook** — even just a session-start hook that prints context. Make the harness DO something, not just DESCRIBE something.
