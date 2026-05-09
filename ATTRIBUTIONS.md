# Attributions

superharness is original work, but many of its design decisions came from studying other open agent harnesses and patterns. This document records what we extracted from each, what we deliberately did not adopt, and where the comparison docs live.

The high-level summary is in the [README "Prior art and influences" section](README.md#prior-art-and-influences). This file is the long form.

---

## Nous Research — hermes-agent

Repo: <https://github.com/nousresearch/hermes-agent>

**Adopted**
- Agent lifecycle and tool-use shape — the loop boundary between "decide" and "act" that shows up in our handoff/dispatch split.
- Plan/report phase separation as a first-class protocol step rather than a free-form prompt convention.

**Did not adopt**
- Hermes' single-agent runtime model. superharness is built around serial multi-agent handoff (Claude, Codex, Gemini, OpenCode), not one process loop.

**Comparison docs**
- [docs/AUDIT-pi-hermes-adaptation.md](docs/AUDIT-pi-hermes-adaptation.md)
- [docs/COMPARISON-superharness-vs-pi-hermes.md](docs/COMPARISON-superharness-vs-pi-hermes.md)
- [docs/hermes-integration-tdd-plan.md](docs/hermes-integration-tdd-plan.md)

---

## earendil-works — pi

Repo: <https://github.com/earendil-works/pi>

**Adopted**
- Multi-agent coordination shape: explicit roles, explicit handoffs, explicit review boundaries.
- The idea that agent identity is a first-class field on every task transition (`from`, `to`, `owner`).

**Did not adopt**
- pi's runtime orchestration model. superharness keeps the orchestrator out-of-process (the watcher), so adapters stay swappable.

**Comparison docs**
- [docs/COMPARISON-superharness-vs-pi-hermes.md](docs/COMPARISON-superharness-vs-pi-hermes.md)

---

## obra — superpowers

Repo: <https://github.com/obra/superpowers>

**Adopted**
- Two-stage review pattern per task: spec compliance first, then code quality. Mapped onto our `report_ready → review_requested → review_passed` transitions.
- TDD enforcement as a first-class field on the plan handoff (`tdd: { red, green, refactor }`).
- Skill-as-context shape: composable `SKILL.md` files that load on situation match.

**Did not adopt**
- Superpowers' "auto-trigger when situation detected" runtime. superharness keeps skill loading explicit so an audit trail exists for every dispatch.

**Comparison docs**
- [docs/CONCEPT-superpowers-extraction.md](docs/CONCEPT-superpowers-extraction.md)

---

## paperclipai — paperclip

Repo: <https://github.com/paperclipai/paperclip>

**Adopted**
- Adapter-family pattern (Claude/Codex/Cursor/Gemini/OpenCode/Pi) as the shape our adapter directory targets.
- Dashboard as a real control plane, not just a viewer — drove the `shux operator start` + `shux dashboard` UX direction.
- Plugin/module formalization as a public surface (work in progress under `shux enhance`).

**Did not adopt**
- Paperclip's "company export" packaging story. superharness stays file-native and project-scoped on purpose; portability lives in `shux pack`, not in a heavier company abstraction.
- Paperclip's broader product surface. superharness is intentionally a CLI-first protocol with a dashboard, not a desktop product.

**Comparison docs**
- [docs/AUDIT-paperclip-gap-analysis.md](docs/AUDIT-paperclip-gap-analysis.md)

---

## Charlie85270 — Dorothy

Repo: <https://github.com/Charlie85270/Dorothy>

**Adopted**
- SQLite + FTS5 as the knowledge/recall backend (drives `shux recall`).
- Kanban surface as a useful operator view of the contract (informs the dashboard layout).

**Did not adopt**
- Dorothy's parallel agent runtime (10+ simultaneous). superharness is serial-by-default to avoid contention; parallelism is opt-in via worktrees.
- Electron desktop packaging. We stay browser-dashboard + CLI.

**Comparison docs**
- [docs/comparison-dorothy.md](docs/comparison-dorothy.md)

---

## Ralph Loops — Chris Parsons / Jeffrey Huntley

Sources:
- Chris Parsons workshop: <https://youtu.be/2TLXsxkz0zI>
- Jeffrey Huntley: <https://ghuntley.com/>

**Adopted**
- "Next most important task" dispatch model. We run continuous lifecycle scans in the watcher (`auto_dispatch` + `inbox_watch`) instead of pre-planned dependency graphs. The agent picks the next priority-unblocked task per iteration.
- Fresh-context discipline. Every dispatch starts with a clean adapter context plus the report handoff from the prior task — forces knowledge to be codified into committed files rather than rotting in session memory.
- Sub-agent validation pattern. The reviewer runs in a fresh sub-context with no implementer history, to defeat confirmation bias on `review_requested`.
- "Reversible without embarrassment" framing for autonomy gates (informs `shux workflow` policy fields and how `auto_dispatch` decides whether to fire without approval).

**Did not adopt**
- The raw `while true; claude -p` runner. It races the watcher and bypasses the `plan_proposed → plan_approved` gate. Our equivalent is `auto_dispatch` inside the supervised lifecycle.
- "Skip the plan, just loop" simplification. We keep TDD plan + review gates because the cost of a bad task at scale is higher than the cost of a plan handoff.

**Inspiration notes**
- [vault: notes/1_ai/youtube_intel/intel/ralph_loops_dumb_ai_loops_that_ship](../) — distilled intel and backlog items from the workshop.

---

## How to add a new attribution

When extracting from a new source:
1. Add a comparison or extraction doc under `docs/` (`COMPARISON-…`, `AUDIT-…`, or `CONCEPT-…`).
2. Add a one-line entry in the README "Prior art and influences" section, linking the doc.
3. Add a long-form section here with **Adopted** / **Did not adopt** / **Comparison docs** subsections.
4. Be specific. "Inspired by X" is not an attribution — name the field, behavior, or pattern.
