# superreins Roadmap

## What "Done" Means

superreins is never feature-complete — it's a living system. But it needs a 1.0 definition or it becomes the ultimate scope-creep project (anti-pattern #2: over-planning as procrastination).

---

## v1.0 Definition — "It works"

superreins is 1.0 when ALL of these are true:

1. **Identity core loads automatically** in every Claude Code and Codex CLI session
2. **Cross-agent protocol is tested** — at least one feature built with Claude planning + Codex implementing, using contract + handoff + ledger
3. **Ship pressure is visible** — days-since-last-ship shows at session start
4. **Failure memory is active** — at least 5 logged failures searchable in vault
5. **One real project runs on it** — not superreins itself, a real venture (VidDocs, RepoSec, etc.)

That's it. Not "all 8 layers are perfectly documented." Not "every skill is executable." One real project using the cross-agent protocol with identity loaded and ship pressure visible.

**Maintenance budget after 1.0:** Max 1 hour/month on harness improvement. Changes are reactive (fix what breaks), not proactive (add what might be nice).

---

## Current: v0.4 — "It has ideas"

### Done
- 8-layer architecture defined
- Identity core (30 lines)
- Cross-agent communication protocol (contract + handoff + ledger)
- Failure memory protocol
- Decision journal protocol
- Context engineering docs
- State protocol with templates
- Research backing from Anthropic, OpenAI, pi.dev

### Not Done
- Nothing is executable yet — all documentation
- agents/ directory has protocol but no agent-specific configs
- templates/ is empty
- No hooks enforce anything
- Ship pressure doesn't exist as a running thing
- No real project uses it

---

## v0.5 — "It has teeth" (next)

Make ONE thing executable per category:

| What | How | Validates |
|------|-----|-----------|
| Identity loads automatically | CLAUDE.md `@imports` identity/core.md | Layer 1 works |
| Ship pressure shows at session start | bash script: `git log --tags --oneline -1` + days math | Original innovation works |
| Contract file gets created for a real feature | Manually create `.superreins/contract.yaml` for one VidDocs feature | Protocol is usable |
| One Codex handoff happens | Claude plans → Codex implements → handoff written | Cross-agent works |
| One failure gets logged and later prevents re-attempt | Log a failure, search for it next session | Failure memory works |

v0.5 is about TESTING, not building more docs.

---

## v0.6 — "It compounds"

- Vault integration tested: /remember reads from contracts + ledger
- /upvault auto-extracts decisions and failures from contract into vault notes
- Energy-based routing tried for 2 weeks (track if it changes behavior)
- 5-minute session protocol tried for 2 weeks (track frequency + value)

---

## v0.7 — "It's portable"

- Second project runs on superreins (not just the first)
- CLAUDE.md template generates correctly for new project
- AGENTS.md template generates correctly for new project
- `.superreins/` directory bootstraps with `superreins init`

---

## v0.8-0.9 — "It's reliable"

- Harness scorecard: monthly self-assessment automated
- Instinct protocol: at least manual pattern documentation
- Pre-commit hook: verifies contract status before allowing commit
- Context budget enforcement: CLAUDE.md line count check

---

## v1.0 — Ship it

All 5 criteria from the top of this file are met.
After 1.0: maintenance mode. 1 hour/month max.

---

## Anti-Scope-Creep Rules for This Roadmap

1. **Each version has max 5 items.** If you can't do it in 5 things, you're planning too much.
2. **v0.5 is about testing, not building.** The docs exist. Test them with real work.
3. **Skip versions if needed.** If v0.6 concepts prove useless during v0.5 testing, drop them.
4. **The roadmap itself has a maintenance budget.** Update it once per version. Not every session.
5. **If you're reading this instead of working on a real project, stop.** superreins exists to make real work better, not to be the work.
