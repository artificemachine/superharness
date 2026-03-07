---
name: cross-agent-review
description: Review AI-generated code using a different agent than the one that wrote it
triggers:
  - code review
  - review output
  - after implementation
  - quality check
---

# Cross-Agent Review

Never review your own AI's code. Let the other agent review it.

## Why

Same model in different harnesses catches different bugs. A Claude Code session reviewing Codex output (or vice versa) has a higher defect detection rate than self-review.

## Workflow

### Step 1: Implementation Complete
The implementing agent (Claude Code or Codex) finishes the task and commits to a feature branch.

### Step 2: Hand Off
Pass the diff or file list to the reviewing agent:

```bash
# Generate review context
git diff main..HEAD > /tmp/review-context.diff
```

### Step 3: Review Checklist
The reviewing agent checks:

1. **Correctness** — Does it do what the spec says?
2. **Security** — Any injection, hardcoded secrets, unsafe patterns?
3. **Edge cases** — What happens with empty input, null, overflow?
4. **Style** — Does it follow project conventions (CLAUDE.md)?
5. **Tests** — Are there tests? Do they cover the happy path + at least one edge case?
6. **Dependencies** — Any new dependencies? Are they justified?

### Step 4: Report
Reviewing agent outputs a structured review:

```
## Review: [feature-name]
- **Verdict:** PASS / PASS WITH NOTES / FAIL
- **Issues found:** [count]
- **Blocking issues:** [list or "none"]
- **Suggestions:** [non-blocking improvements]
```

### Step 5: Fix
If FAIL: implementing agent fixes issues, then re-review.
If PASS WITH NOTES: fix non-blocking items at implementer's discretion.

## Rules

- Claude Code reviews Codex output. Codex reviews Claude Code output.
- Review happens BEFORE merge to main.
- Security findings are always blocking.
- Don't skip review to save time. The bugs you catch here cost 10x more later.
