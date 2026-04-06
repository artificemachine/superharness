# superharness — Improvements

> What would make superharness better for its actual users, prioritized by pain and leverage.
>
> Last updated: 2026-03-30

---

## 1. New Capabilities (not on any existing roadmap)

These are gaps discovered by comparing against pi.dev and Dorothy, and from real usage friction.

### `shux diff` — what actually changed

Before `shux close`, show a git diff summary of what changed during the task. Today there's a gap between "what the agent reported in the handoff" and "what actually changed in the repo." This would close that loop and catch cases where an agent claims success but the diff tells a different story.

### `shux global-status` — multi-project overview

Each project has its own `.superharness/`. There's no way to see across all of them. A `shux global-status` that scans registered projects (from `~/.git-push-allowlist` or a new registry) would replace the manual per-project checks done during morning briefings.

### Semantic recall

`shux recall` is grep over YAML files. Works fine at small scale, breaks down as the ledger and handoff archive grow. Embedding-based search (local, via `llm` CLI or sqlite-vec) would surface relevant past decisions that grep misses because the query terms don't match verbatim.

### Task templates

Common task types (bugfix, feature, refactor) share the same TDD structure. Pre-packaged templates would eliminate the repetitive setup:

```bash
shux task create --from-template bugfix --id fix-auth --title "Fix token refresh"
```

### `shux fork <handoff-id>` — branch from past context

Create a new task pre-loaded with a prior handoff's context. Useful when a completed task spawns follow-up work — instead of manually copying context, fork the handoff and edit the scope.

### Cost dashboard in dashboard

`cost_estimator.py` already estimates token costs per subtask. Surface this in the dashboard — cumulative cost per task, per day, per agent. Low effort, high visibility.

---

## 2. Harden what exists

### `shux discuss` — close the gaps

The discussion protocol is fully implemented (6 CLI subcommands, 9 engine commands, discussion dispatch poller). But it has known limitations worth addressing:

| Gap | Impact |
|-----|--------|
| No staleness timeout — discussions stay "active" forever if an agent doesn't submit | Stale discussions accumulate silently |
| No verdict validation — accepts any string as a verdict | Inconsistent data in round files |
| No dispute resolution — max rounds reached = closed with no recommended action | Operator gets no guidance on deadlocked discussions |
| No audit log — approvals recorded in handoff/contract only | No single place to review approval history |

### `shux doctor` — module suggestions

When `shux doctor` detects tools on the system (shipguard, obsidian vault, ntfy), suggest the corresponding module: "shipguard found — run `shux enhance enable security`". Requires the module system (see section 3).

---

## 3. Execute the existing roadmap

These are already scoped with TDD plans. Not restated here — just the priority call.

| What | Reference | Why it matters |
|------|-----------|----------------|
| **Module system iters 0–2** | `plan-module-system.md` | Foundation that unlocks obsidian, security, ntfy, and all future modules. Without this, every integration is a one-off hack. |
| **Module system iters 3, 6** (obsidian + remember) | `plan-module-system.md` | Closes the knowledge loop — vault notes on close, context refresh on continue. Core value prop. |
| **always-on-agent daemon mode** | `ROADMAP.md` | `shux daemon start` replaces the brittle launchd/systemd install scripts. Single biggest DX pain point for watcher setup. |
| **always-on-agent cron + model fallback** | `ROADMAP.md` | Cron enables scheduled tasks without external crontab. Model fallback adds resilience (Sonnet → Haiku on budget). |
| **Parallel dispatch + worktrees** | ✅ Implemented v1.7.0 | `fanout_dispatch()` + `swarm_dispatch()` with git worktrees, Opus reviewer, try/finally cleanup. |

---

## 4. Deliberate non-goals

Features other tools have that superharness intentionally does not pursue:

| Feature | Who has it | Why not |
|---------|-----------|---------|
| **Agent/provider neutrality** (15+ providers) | pi.dev | superharness dispatches to `claude` and `codex` CLIs — the two best coding agents. Adding aider/cursor adapters would increase maintenance surface for tools the project owner doesn't use. Revisit only if a concrete user requests it. |
| **Desktop GUI** (Electron app) | Dorothy | Conflicts with the "works over SSH, in CI, headless" design principle. The dashboard at `:8787` covers the visual needs without an Electron dependency. |
| **Enterprise integrations** (JIRA, Figma, Vercel) | Dorothy | superharness targets solo devs with limited bandwidth, not enterprise teams. These integrations are maintenance-heavy and outside the core value prop. |
| **Shareable extension packages** (npm marketplace) | pi.dev | The module system uses YAML templates, not packaged code. Community distribution (`gh:user/module`) is interesting but premature — build the module system first, then see if there's demand. |

---

## 5. Priority order (with rationale)

| # | Improvement | Why this position |
|---|-------------|-------------------|
| 1 | Module system iters 0–2 | Unlocks everything — obsidian, security, ntfy, and future modules all depend on this. Highest leverage. |
| 2 | Module system iters 3, 6 (obsidian + remember) | Directly strengthens the core value prop: cross-session memory. Each close writes to the vault, each continue loads context. |
| 3 | `shux diff` | Small scope, high trust payoff. Verifying agent work before close prevents silent failures from compounding across sessions. |
| 4 | Daemon mode (always-on-agent merge) | Removes the most common onboarding friction. launchd plists are brittle and OS-specific; `shux daemon start` is portable. |
| 5 | `shux discuss` hardening | Already implemented — just needs staleness timeout and verdict validation. Small effort, prevents data quality rot. |
| 6 | Cost dashboard | Low effort — `cost_estimator.py` exists, just needs a `/api/costs` endpoint and a panel in the dashboard. |
| 7 | `shux global-status` | Becomes more valuable as the number of superharness-managed projects grows. Not urgent at 2–3 projects. |
| 8 | Semantic recall | Grep works fine below ~200 handoffs. Worth doing when the archive outgrows keyword search. |
| 9 | Task templates | Convenience, not blocking. The Enqueue modal already assembles TDD instructions per task. |
| 10 | Cron + model fallback (always-on-agent) | Useful but not blocking anything. Cron jobs can use system crontab in the meantime. |
| 11 | `shux fork` | Nice workflow shortcut. Manual copy-paste of handoff context works today. |
| 12 | Parallel dispatch + worktrees | ✅ Implemented v1.7.0 — `fanout_dispatch()`, `swarm_dispatch()`, git worktrees, Opus reviewer. |

---

## References

- `docs/comparison-dorothy.md` — Dorothy vs. superharness (2026-03-20)
- `docs/plan-module-system.md` — Module system TDD plan (12 iterations)
- `docs/ROADMAP.md` — always-on-agent merge + worktree design
- [pi.dev](https://pi.dev/) — minimal terminal coding agent
