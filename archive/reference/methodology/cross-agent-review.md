# Cross-Agent Review — Layer 5

The agent that wrote the code is worst at reviewing it. Use a different agent.

---

## When to Cross-Review

- Before merging any feature branch
- After Codex batch generation → Claude Code reviews
- After Claude Code refactoring → Codex reviews
- Before shipping to production → always
- After any AI-generated code > 100 lines

---

## The Pattern

```
Author agent: implements the feature
  → writes code, tests, documentation
  → commits to feature branch

Reviewer agent: reviews the diff
  → receives: git diff, test results, CLAUDE.md architecture rules
  → does NOT receive: the full conversation, the author's reasoning
  → checks: correctness, edge cases, architecture, security, readability