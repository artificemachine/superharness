# Context Engineering — Layer 7

Context engineering is the discipline of controlling what an LLM sees before it generates a single token. It's the highest-leverage skill a solo dev can build, because context quality determines output quality more than model choice.

---

## The Four Operations

(Source: Anthropic — "Effective Context Engineering for AI Agents")

### 1. Write — Externalize to Files
When context is too large for the window, write it to a file and reference it.

- Progress files → `state/progress.md` (current task state)
- Plans → `state/plan.md` (what we're building and why)
- Decisions → commit messages, vault notes (why we chose X over Y)

The file system is infinite memory. The context window is not.

### 2. Select — Inject Only What's Relevant
Give the agent ONLY the information it needs for its current step.

- CLAUDE.md is a table of contents, not an encyclopedia
- Use `@imports` to pull in specific sections on demand
- Search vault BEFORE implementing (mid-session retrieval, not just /remember at start)
- Tool results: filter before returning. Don't dump raw JSON.

### 3. Compress — Summarize Before Returning
Sub-agents and tool calls should return summaries, not raw output.

- Sub-agent pattern: task → execute → return 3-5 line summary
- Search results: extract relevant lines, not full documents
- Code review: return findings + line numbers, not entire file contents
- Vault queries: return note titles + 1-line relevance, not full note text

### 4. Isolate — Lean Context Per Sub-Agent
Each sub-agent gets only what it needs. Don't inherit the parent's full context.

- Cross-agent review: reviewer gets the diff + test results, not the full conversation
- Batch generation: each Codex task gets its own AGENTS.md + target spec, nothing else
- Worktree isolation: each agent in its own git worktree, own branch

---

## The 60% Rule

Past ~60% context window utilization, agent performance degrades. This is "context rot."

**Budget for a ~200K token window:**
- System prompt + CLAUDE.md: ~5K tokens (keep under 200 lines)
- Tool definitions: ~10K tokens (automatic, can't control)
- Identity core: ~500 tokens (~30 lines)
- Task context: remaining budget for actual work

**What silently eats tokens:**
- Verbose tool results (full file reads when you needed 3 lines)
- Accumulated conversation history (compaction is lossy)
- MCP server definitions (each server adds overhead)
- Previous sub-agent results left in context

---

## Anti-Rot Protocol

Compaction is lossy compression. A 50-line architectural discussion becomes one sentence. The "why" disappears.

### Before Compaction
1. Write current state to `state/progress.md`
2. Write current plan to `state/plan.md`
3. Write remaining tasks to `state/tasks.md`
4. These files survive compaction — the agent reads them to recover

### During Long Sessions
- Checkpoint every 30 minutes of heavy work
- After any major decision, write the decision + reasoning to a file
- Before starting a new phase, re-read progress files
- If the agent seems confused after compaction → "Read state/progress.md and continue"

### Cache Optimization
- Keep CLAUDE.md stable (cache-friendly — same prefix = cache hit)
- Don't rewrite CLAUDE.md mid-session
- Front-load the most important context (identity core first, details last)
- Anthropic's prompt caching: identical prefixes are cached, changes invalidate

---

## Practical Rules

1. **Every CLAUDE.md line must change agent behavior.** If removing a line doesn't make output worse, delete it.
2. **Target under 200 lines per CLAUDE.md.** Use @imports for detail.
3. **Sub-agents return summaries.** Never raw dumps.
4. **Search before implementing.** Mid-session vault query prevents re-solving solved problems.
5. **Write decisions to files.** Context window forgets. Files don't.
6. **Checkpoint before deep work.** If compaction might hit during this task, write state first.
