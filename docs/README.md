# superharness — Documentation Index

> Updated 2026-09-18. Run the `docs-organize` skill to audit. On 2026-09-10, 43 superseded or completed docs (~8,150 lines) were pruned: 16 unlinked files under `archive/` plus 27 completed plans/audits/reviews that had been listed in this index. The 4 prior-art analyses cited from the root README's "Prior art" section remain tracked.

---

## 🚀 Onboarding

| Doc | What |
|-----|------|
| [`README.md`](../README.md) | Project overview, quickstart |
| [`INSTALL-AGENT.md`](guides/INSTALL-AGENT.md) | Installation guide for agents |
| [`GUIDE.md`](GUIDE.md) | Full command and dashboard appearance reference |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Contributing guide, test instructions |
| [`DISCUSS.md`](reference/DISCUSS.md) | Multi-agent discussion protocol |
| [`WHY-TUI.md`](concepts/WHY-TUI.md) | Why a TUI for superharness |
| [`UNATTENDED.md`](guides/UNATTENDED.md) | Overnight unattended agent execution |

## 🏗 Architecture & Design

| Doc | What |
|-----|------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Architecture overview and design decisions |
| [`ARCH-superharness-design-patterns.md`](arch/ARCH-superharness-design-patterns.md) | Current architecture and the proposed hexagonal target (Mermaid); `reconcile` extraction first |
| [`DESIGN-risky-choices.md`](archive/DESIGN-risky-choices.md) | Documented sharp edges and risky choices |
| [`ROADMAP-phases.md`](plans/ROADMAP-phases.md) | **Master phase roadmap** (single source of truth) |
| [`IMPLEMENTATION-status.md`](archive/IMPLEMENTATION-status.md) | Implementation status across all audits |
| [`ANALYSIS-sqlite-doctrine-drift.md`](archive/ANALYSIS-sqlite-doctrine-drift.md) | How the SQLite doctrine drifted, and how to make it un-driftable |
| [`brain-multi-agent-tiers-fleet.md`](reports/brain-multi-agent-tiers-fleet.md) | Why 4 agent CLIs, what tiers mean, Ollama + vLLM fleet |
| [`brain-scan-2026-07-12.md`](reports/brain-scan-2026-07-12.md) | Brain-level scan of superharness (2026-07-12) |
| [`fleet-vllm-enablement.md`](guides/fleet-vllm-enablement.md) | vLLM per-tier fleet endpoints — enablement guide |
| [`observability-spec-d2.md`](reference/observability-spec-d2.md) | Observability specification (D2) |
| [`langfuse-observability.md`](guides/langfuse-observability.md) | Optional privacy-first Langfuse telemetry and dashboard link behavior |
| [`TEST_STRATEGY.md`](guides/TEST_STRATEGY.md) | Test strategy overlay for superharness |

## 📐 Concepts & Designs

| Doc | What |
|-----|------|
| [`CONCEPT-recall-progressive-disclosure.md`](concepts/CONCEPT-recall-progressive-disclosure.md) | 3-layer recall progressive disclosure |
| [`CONCEPT-sdk-vs-cli.md`](concepts/CONCEPT-sdk-vs-cli.md) | SDK vs CLI dispatch paths |
| [`CONCEPT-behavioral-profile.md`](concepts/CONCEPT-behavioral-profile.md) | Zero-touch adaptive layer — behavioral profile |
| [`CONCEPT-notifications-and-state-isolation.md`](concepts/CONCEPT-notifications-and-state-isolation.md) | Notifications + state isolation concept |
| [`CONCEPT-content-addressed-context-typed-boundaries.md`](concepts/CONCEPT-content-addressed-context-typed-boundaries.md) | Content-addressed context hashing + typed handoff boundaries |
| [`CONCEPT-openprose-reactor.md`](concepts/CONCEPT-openprose-reactor.md) | OpenProse/Reactor adaptation, SDD conditions and pilot gates (merged 2026-09-18) |
| [`CONCEPT-develop-until-approved.md`](concepts/CONCEPT-develop-until-approved.md) | Pi-style `developIssuesUntilApproved` orchestration (includes the former FLOW as Appendix A) |

## 🔒 Security & Audits

| Doc | What |
|-----|------|
| [`gateway-security.md`](security/gateway-security.md) | Notification gateway security audit |
| [`SECURITY-autonomous-dispatch.md`](security/SECURITY-autonomous-dispatch.md) | Autonomous dispatch security gates |
| [`yaml-inventory.md`](reference/yaml-inventory.md) | YAML file inventory post phase-4 cleanup |

## 🔎 Audits (Runtime & Protocol)

| Doc | What |
|-----|------|
| [`CLASSIFY-discussion-tier-effort.md`](archive/CLASSIFY-discussion-tier-effort.md) | Task & discussion tier/effort classification |
| [`COMPARE-ltx2-train-model-skill-vs-lifecycle.md`](archive/COMPARE-ltx2-train-model-skill-vs-lifecycle.md) | LTX-2 `train-model` skill vs the superharness lifecycle |
| [`ADOPTION-LIST-omnigent-2026-07-19.md`](archive/ADOPTION-LIST-omnigent-2026-07-19.md) | Adoption list — omnigent → superharness (2026-07-19) |
| [`audits/2026-09-18-docs-triage.md`](audits/2026-09-18-docs-triage.md) | docs/ merge and archive triage — what was merged, archived, and deliberately left |
| [`audits/2026-09-10-arch-audit.md`](audits/2026-09-10-arch-audit.md) | Architecture audit — current run (0 critical, 3 high, 4 medium, 4 low) |
| [`archive/2026-08-05-arch-audit.md`](archive/2026-08-05-arch-audit.md) | Architecture audit — superseded run (2026-08-05) |
| [`archive/2026-07-21-arch-audit.md`](archive/2026-07-21-arch-audit.md) | Architecture audit — superseded run (2026-07-21) |
| [`archive/2026-08-05-bulletproof.md`](archive/2026-08-05-bulletproof.md) | Claims-vs-reality run — superseded (2026-08-05) |

## 📋 Plans (Active)

| Doc | What |
|-----|------|
| **Task Lifecycle** | |
| [`plan-subtask-resolution-gate.md`](plans/plan-subtask-resolution-gate.md) | Subtask resolution gate plan |
| **Memory / Learning** | |
| [`plans/PLAN-superharness-L5.md`](plans/PLAN-superharness-L5.md) | Superharness L5: close G5c, wire dormant learning loops |
| **Infrastructure** | |
| [`windows-native-full-fix-tdd-plan.md`](plans/windows-native-full-fix-tdd-plan.md) | Native Windows fix TDD plan |
| [`plans/harness-phi4mini-redesign.md`](plans/harness-phi4mini-redesign.md) | phi4-mini/Ollama harness — redesign against main |
| **Module / Feature** | |
| [`PROPOSAL-session-injection-discussion-dispatch.md`](concepts/PROPOSAL-session-injection-discussion-dispatch.md) | Session injection for discussion dispatch |
| **Subsystem Plans** | |
| [`plans/workflow-autonomy.md`](plans/workflow-autonomy.md) | Workflow + per-project autonomy |

## 🔍 Reviews

| Doc | What |
|-----|------|
| [`senior-review-2026-05-20.md`](reports/senior-review-2026-05-20.md) | Senior review — 11 fixes, C4-C6 decomposition |
| [`SKILL_GENERICITY_REVIEW.md`](reports/SKILL_GENERICITY_REVIEW.md) | Skill genericity review (2026-05-26) |

## 🐛 Bugs

| Doc | What |
|-----|------|
| [`bugs/2026-05-11_discuss_dispatch_bugs.md`](bugs/2026-05-11_discuss_dispatch_bugs.md) | Discuss dispatch bugs through v1.56.2 |
| [`bugs/2026-05-21_ai-driven-dispatch-failure.md`](bugs/2026-05-21_ai-driven-dispatch-failure.md) | Why `ai_driven` autonomy did not dispatch (morpheme project) |
| [`bugs/2026-05-21_discuss_cli_ux_bugs.md`](bugs/2026-05-21_discuss_cli_ux_bugs.md) | `shux discuss` UX and retry-alert bugs (v1.62.20) |
| [`bugs/BUG-2026-06-04-operator-orphans-pytest-swap-storm.md`](bugs/BUG-2026-06-04-operator-orphans-pytest-swap-storm.md) | Operator orphans pytest → 34 GB swap storm |
| [`bugs/BUG-2026-07-31-test-suite-git-dir-escape.md`](bugs/BUG-2026-07-31-test-suite-git-dir-escape.md) | Test suite escaped into the real repo `.git/config` (`core.bare`, `core.hooksPath`) |
| [`bugs/BUG-2026-09-18-inbox-watch-reviewer-tier-gate.md`](bugs/BUG-2026-09-18-inbox-watch-reviewer-tier-gate.md) | Auto-review tier gate is not enforced; the function meant to enforce it raises `ImportError` |
| [`bugs/BUG-2026-09-18-state-db-skeleton-leak.md`](bugs/BUG-2026-09-18-state-db-skeleton-leak.md) | Every project path ever seen gets a 340 KB empty `state.db`; `shux state gc` reports them, deletes nothing |
| [`bugs/BUGREPORT-discussion-consensus-single-participant.md`](bugs/BUGREPORT-discussion-consensus-single-participant.md) | Discussion consensus reached with only 1 of 3 participants |
| [`bugs/BUGREPORT-watcher-silent-death-no-recovery.md`](bugs/BUGREPORT-watcher-silent-death-no-recovery.md) | Watcher silent death — no auto-recovery (19+ hour outage) |
| [`bugs/discussion-dispatch-tier-ignored-double-failure.md`](bugs/discussion-dispatch-tier-ignored-double-failure.md) | Discussion dispatch fails twice — max tier ignored, silent failures |
| [`bugs/gemini-discussion-dispatch-silent-failure.md`](bugs/gemini-discussion-dispatch-silent-failure.md) | Gemini-CLI discussion dispatch fails silently |
| [`bugs/watcher-dies-between-sessions.md`](bugs/watcher-dies-between-sessions.md) | Watcher dies between sessions — root cause report |

## 🧾 Bulletproof / Verification Reports

Point-in-time claim-vs-reality audits. `docs/bulletproof-report-*.md` is gitignored (working-notes pattern, matches `.gitignore`) — reports are never git-tracked and can't be linked here. Run `/bulletproof` to generate the latest one locally; check `docs/archive/` for historical superseded runs kept before this pattern was adopted.

## 📐 Specifications & References

| Doc | What |
|-----|------|
| [`specs/state-backend-interfaces.md`](specs/state-backend-interfaces.md) | State backend interfaces (authoritative) |
| [`adapter-payload-spec.md`](reference/adapter-payload-spec.md) | Adapter payload JSON schema |
| [`adapter-models.md`](reference/adapter-models.md) | Adapter model-to-tier mapping |
| [`pack-format.md`](reference/pack-format.md) | shux pack archive format |
| [`MCP-MEMORY.md`](reference/MCP-MEMORY.md) | Optional MCP memory server setup |
| [`archive/morpheme-branch-policy.md`](archive/morpheme-branch-policy.md) | Morpheme branch policy (retired 2026-04-16; archived 2026-09-18) |

## 📎 Reports & Misc

| Doc | What |
|-----|------|
| [`REPO-MIGRATION-fork-situation.md`](reports/REPO-MIGRATION-fork-situation.md) | Repo migration — `celstnblacc` → `artificemachine` fork situation |
| [`REPORT-process-leak-2026-05-28.md`](reports/REPORT-process-leak-2026-05-28.md) | Process leak incident report |

---

## 📦 Archived (32 files in `docs/archive/`)

Obsolete, completed, superseded, or dated docs moved to archive. See `docs/archive/` for:
- Session handoff notes (`HANDOFF-2026-06-*.md`, `NEXT_SESSION_HANDOFF.md`, `handoff-yaml-cleanup-session-2026-05-13.md`)
- Superseded bulletproof-report runs (the 2026-05-24 series, superseded by the active reports above)
- A dated release checklist (`RELEASE-TODO-v1.62.15.md`)
- Completed migration/cleanup plans (SQLite migration, contract-YAML removal, module system, onboarding pipeline)
- Stale comparisons/audits/reviews (pi-hermes comparison, Dorothy comparison, drift audit)
- Superseded dated audits (the 2026-07-21 and 2026-08-05 architecture audits and the 2026-08-05 bulletproof run, archived 2026-09-18 behind the 2026-09-10 audit) and the retired morpheme branch policy

---

**Last updated:** 2026-09-10 | **Active docs:** 63 | **Archived:** 28
