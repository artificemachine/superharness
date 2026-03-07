# Agent Context — Maxime Roy

> This is the hub document. Embed the identity core into your global CLAUDE.md.
> Import detailed sections as needed. Do NOT load everything at once.

---

## Identity Core
→ See `identity/core.md` (~30 lines — always loaded)

## Full Developer Profile
→ See `identity/developer-profile.md` (load when you need tech stack, domain expertise, or venture details)

## Task Routing
→ See `methodology/routing.md` (load when deciding which agent/model handles a task)

## Session Templates
→ See `methodology/session-discipline.md` (load at session start/end)

## Ship Pipeline
→ See `methodology/ship-pipeline.md` (load before committing or shipping)

## Cross-Agent Review
→ See `methodology/cross-agent-review.md` (load before merge)

## Context Engineering
→ See `context/context-engineering.md` (load when managing long sessions)

## State Protocol
→ See `state/state-protocol.md` (load when checkpointing or recovering)

## Vault Protocol
→ See `knowledge/vault-protocol.md` (load for /remember, /upvault, or mid-session search)

---

## Quick Reference — What Matters Most

**Who:** Maxime Roy. Solo dev, 15+ yrs C++/Python/Rust. 10-20 hrs/week side projects.

**Anti-patterns:** Scope creep → over-planning → shiny objects. Guard against all three.

**Session rule:** One task. /remember at start. /upvault at end. Plan at END not start.

**Ship rule:** Security scan first. Never --no-verify. Cross-agent review before merge.

**Context rule:** CLAUDE.md under 200 lines. Sub-agents return summaries. Files > window.

**Tools:** Claude Code (collaborator) + Codex CLI (contractor) + Cowork (knowledge work).

**Model escalation:** Haiku → Sonnet (default) → Opus (only after Sonnet fails 2×).

---

*This document is ~50 lines. That's intentional. The old version was 139 lines mixing everything inline. Each section now lives in its own file, loaded on demand. Context is finite — spend it on the task, not on the instructions.*
