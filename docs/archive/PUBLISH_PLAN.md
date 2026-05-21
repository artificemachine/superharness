# Blog Publishing Plan

Publish the comparison article on Dev.to (primary) and GitHub Discussions (repo audience).

---

## Pre-publish Checklist

| Step | Done? |
|------|-------|
| Merge PR #7 to main | |
| PyPI publishing live (`pipx install superharness` works) | |
| Review `docs/blog-comparison-draft.md` for accuracy | |
| Create Dev.to account | |

---

## Part 1: Dev.to

### 1a. Create Account
1. Go to https://dev.to/enter
2. Sign up with GitHub (recommended — links to your profile)
3. Complete profile: name, bio ("Building superharness — multi-agent coordination for AI coding assistants"), profile picture

### 1b. Prep the Article
1. Click **"Create Post"** (top-right)
2. Paste the content from `docs/blog-comparison-draft.md`
3. Add this frontmatter at the top of the editor:

```
---
title: What Anthropic Gets Right About AI Agent Harnesses — and What's Missing
published: true
tags: ai, python, opensource, productivity
series:
canonical_url:
cover_image:
---
```

### 1c. Formatting Tweaks for Dev.to
- Dev.to uses standard markdown — the draft should render as-is
- The comparison table renders natively
- Add a cover image if you have one (1000x420px recommended) — otherwise skip it
- Preview the post before publishing (Dev.to has a preview tab)

### 1d. Publish
1. Click **"Publish"**
2. Copy the published URL (e.g. `https://dev.to/celstnblacc/what-anthropic-gets-right-...`)
3. Save this URL — you'll need it for GitHub Discussions and README

### 1e. Post-publish on Dev.to
- Respond to any comments in the first 24-48 hours (Dev.to algorithm rewards engagement)
- Pin the post to your Dev.to profile

---

## Part 2: GitHub Discussions

### 2a. Enable Discussions (if not already)
1. Go to https://github.com/celstnblacc/superharness/settings
2. Scroll to **Features** section
3. Check **Discussions**

### 2b. Create the Discussion Post
1. Go to https://github.com/celstnblacc/superharness/discussions/new
2. Category: **Announcements** (or **General** if Announcements doesn't exist)
3. Title: `superharness vs Anthropic's harness approach — what's different`
4. Body:

```markdown
We published a comparison of superharness with the approach described in
Anthropic's "Effective Harnesses for Long-Running Agents" article.

**TL;DR:** Anthropic solves session continuity (one agent across sessions).
superharness solves agent coordination (multiple agents on the same project).

Read the full post: [DEV.TO_URL_HERE]

Key differences:
- Shared contract + handoffs vs agent-specific memory
- Structured verification gate before closing tasks
- Auto model routing (route tasks to cheapest capable model)
- Background watcher with queue-based dispatch (launchd + systemd)
- Multi-agent discussion protocol for design decisions

Questions or feedback? Reply here or open an issue.
```

5. Click **Start discussion**
6. **Pin the discussion** (click the pin icon on the post)

---

## Part 3: Link Back from README (optional)

Add a line to README.md under Quick Links:

```markdown
📝 **[Blog: superharness vs Anthropic](DEV.TO_URL_HERE)** — Why multi-agent coordination needs more than session memory
```

---

## Part 4: Reddit Cross-post (optional, high reach)

Post the Dev.to link to these subreddits:

| Subreddit | Title suggestion | Flair |
|-----------|-----------------|-------|
| r/ClaudeAI | "Built an open-source harness for running Claude Code + Codex CLI on the same project" | Show and Tell |
| r/Python | "superharness — multi-agent coordination framework for AI coding assistants (Python)" | Show and Tell |

**Reddit tips:**
- Don't just drop a link — write 2-3 sentences about what it does and why you built it
- Reply to comments promptly
- Don't post to both subreddits on the same day (feels spammy)

---

## Timeline

| Day | Action |
|-----|--------|
| Day 1 | Create Dev.to account, publish article |
| Day 1 | Create GitHub Discussion, pin it |
| Day 2 | Post to r/ClaudeAI |
| Day 3-4 | Post to r/Python |
| Day 7 | Check engagement, respond to comments |

---

## Files Reference

| File | Purpose |
|------|---------|
| `docs/blog-comparison-draft.md` | Source article (in repo) |
| `docs/PUBLISH_PLAN.md` | This plan (gitignored) |
| `docs/PYPI_SETUP.md` | PyPI setup steps (gitignored) |
