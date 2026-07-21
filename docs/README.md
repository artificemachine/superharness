# superharness — Documentation Index

> Updated 2026-07-22. Run `docs-organize` skill to audit. 18 internal working docs (`PLAN-*`/`AUDIT-*`/`bulletproof-report-*` matching `.gitignore`) untracked from the public tree; 6 one-off analysis docs (`ANALYSIS-*`/`CLASSIFY-*`/`COMPARE-*`/`DESIGN-*`/`IMPLEMENTATION-*`/`STEAL-*`) moved to `archive/`. The 4 prior-art analyses cited from the root README's "Prior art" section stay tracked.

---

## 🚀 Onboarding

| Doc | What |
|-----|------|
| [`README.md`](../README.md) | Project overview, quickstart |
| [`INSTALL-AGENT.md`](INSTALL-AGENT.md) | Installation guide for agents |
| [`GUIDE.md`](GUIDE.md) | Full command reference (792 lines) |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contributing guide, test instructions |
| [`PYPI_SETUP.md`](PYPI_SETUP.md) | pipx install via OIDC |
| [`DISCUSS.md`](DISCUSS.md) | Multi-agent discussion protocol |
| [`WHY-TUI.md`](WHY-TUI.md) | Why a TUI for superharness |
| [`UNATTENDED.md`](UNATTENDED.md) | Overnight unattended agent execution |

## 🏗 Architecture & Design

| Doc | What |
|-----|------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Architecture overview and design decisions |
| [`DESIGN-risky-choices.md`](archive/DESIGN-risky-choices.md) | Documented sharp edges and risky choices |
| [`ROADMAP-phases.md`](ROADMAP-phases.md) | **Master phase roadmap** (single source of truth) |
| [`IMPLEMENTATION-status.md`](archive/IMPLEMENTATION-status.md) | Implementation status across all audits |
| [`improvement-roadmap.md`](improvement-roadmap.md) | Morpheme + superharness improvement roadmap |
| [`improvement-tdd-plans.md`](improvement-tdd-plans.md) | Improvement TDD plans per PR |
| [`ANALYSIS-sqlite-doctrine-drift.md`](archive/ANALYSIS-sqlite-doctrine-drift.md) | How the SQLite doctrine drifted, and how to make it un-driftable |
| [`brain-multi-agent-tiers-fleet.md`](brain-multi-agent-tiers-fleet.md) | Why 4 agent CLIs, what tiers mean, Ollama + vLLM fleet |
| [`brain-scan-2026-07-12.md`](brain-scan-2026-07-12.md) | Brain-level scan of superharness (2026-07-12) |
| [`fleet-vllm-enablement.md`](fleet-vllm-enablement.md) | vLLM per-tier fleet endpoints — enablement guide |
| [`observability-spec-d2.md`](observability-spec-d2.md) | Observability specification (D2) |
| [`TEST_STRATEGY.md`](TEST_STRATEGY.md) | Test strategy overlay for superharness |

## 📐 Concepts & Designs

| Doc | What |
|-----|------|
| [`CONCEPT-agent-owned-tools.md`](CONCEPT-agent-owned-tools.md) | Agent mutates its own tools mid-task |
| [`CONCEPT-claude-mem-integration.md`](CONCEPT-claude-mem-integration.md) | Claude-mem features worth borrowing |
| [`CONCEPT-inbox-queue-unification.md`](CONCEPT-inbox-queue-unification.md) | Inbox queue unification options |
| [`CONCEPT-quota-and-health.md`](CONCEPT-quota-and-health.md) | Unified quota and health engine |
| [`CONCEPT-recall-progressive-disclosure.md`](CONCEPT-recall-progressive-disclosure.md) | 3-layer recall progressive disclosure |
| [`CONCEPT-sdk-vs-cli.md`](CONCEPT-sdk-vs-cli.md) | SDK vs CLI dispatch paths |
| [`CONCEPT-superpowers-extraction.md`](CONCEPT-superpowers-extraction.md) | Superpowers → superharness extraction |
| [`CONCEPT-behavioral-profile.md`](CONCEPT-behavioral-profile.md) | Zero-touch adaptive layer — behavioral profile |
| [`CONCEPT-notifications-and-state-isolation.md`](CONCEPT-notifications-and-state-isolation.md) | Notifications + state isolation concept |

## 🔒 Security & Audits

| Doc | What |
|-----|------|
| [`gateway-security.md`](gateway-security.md) | Notification gateway security audit |
| [`SECURITY-autonomous-dispatch.md`](SECURITY-autonomous-dispatch.md) | Autonomous dispatch security gates |
| [`defense_layers_plan.md`](defense_layers_plan.md) | Defense layers TDD iteration plan |
| [`AUDIT-claude-mem-adaptation.md`](AUDIT-claude-mem-adaptation.md) | Claude-mem adaptation audit |
| [`AUDIT-paperclip-gap-analysis.md`](AUDIT-paperclip-gap-analysis.md) | Superharness vs Paperclip gap analysis |
| [`AUDIT-pi-hermes-adaptation.md`](AUDIT-pi-hermes-adaptation.md) | **Pi-Mono + Hermes adaptation audit** (ground truth) |
| [`AUDIT-hydra-security-review.md`](AUDIT-hydra-security-review.md) | Hydra security review |
| [`yaml-inventory.md`](yaml-inventory.md) | YAML file inventory post phase-4 cleanup |

## 🔎 Audits (Runtime & Protocol)

| Doc | What |
|-----|------|
| [`AUDIT-2026-06-07-task-discussion-failure.md`](AUDIT-2026-06-07-task-discussion-failure.md) | Why task/discussion create+manage fails (2026-06-07) |
| [`AUDIT-2026-07-09-discussion-close-data-loss.md`](AUDIT-2026-07-09-discussion-close-data-loss.md) | `discussion close` orphans agents and discards output |
| [`AUDIT-discussion-verdict-consensus.md`](AUDIT-discussion-verdict-consensus.md) | `shux discussion` verdict semantics and consensus soundness |
| [`CLASSIFY-discussion-tier-effort.md`](archive/CLASSIFY-discussion-tier-effort.md) | Task & discussion tier/effort classification |
| [`COMPARE-ltx2-train-model-skill-vs-lifecycle.md`](archive/COMPARE-ltx2-train-model-skill-vs-lifecycle.md) | LTX-2 `train-model` skill vs the superharness lifecycle |
| [`STEAL-LIST-omnigent-2026-07-19.md`](archive/STEAL-LIST-omnigent-2026-07-19.md) | Steal list — omnigent → superharness (2026-07-19) |

## 📋 Plans (Active)

| Doc | What |
|-----|------|
| **Hermes / Pi-Mono** | |
| [`hermes-integration-tdd-plan.md`](hermes-integration-tdd-plan.md) | Hermes integration TDD iterations |
| **Paperclip** | |
| **Omnigent** | |
| [`PLAN-steal-omnigent.md`](PLAN-steal-omnigent.md) | Omnigent steal-list implementation |
| **Claude-Mem** | |
| [`PLAN-claude-mem-integration.md`](PLAN-claude-mem-integration.md) | Claude-mem integration iteration plan |
| **Ralph** | |
| **Auto-Mode / Dispatch** | |
| [`auto-mode-gap-v2.md`](auto-mode-gap-v2.md) | Auto-mode gap analysis v2 |
| [`auto-mode-gap-plan.md`](auto-mode-gap-plan.md) | Auto-mode TDD implementation plan |
| [`PLAN-fix-task-discussion.md`](PLAN-fix-task-discussion.md) | Fixes for AUDIT-2026-06-07 task/discussion failures |
| [`PLAN-mvf.md`](PLAN-mvf.md) | Make discussions reach consensus (MVF) |
| **Task Lifecycle** | |
| [`plan-subtask-resolution-gate.md`](plan-subtask-resolution-gate.md) | Subtask resolution gate plan |
| [`design-task-lifecycle-ship.md`](design-task-lifecycle-ship.md) | Ship step in task lifecycle |
| [`plan-task-workflow-v2.md`](plan-task-workflow-v2.md) | Task workflow v2 implementation |
| [`PLAN-issue-link.md`](PLAN-issue-link.md) | GitHub/GitLab issue linking for shux tasks |
| **Memory / Learning** | |
| [`PLAN-memory-distillation.md`](PLAN-memory-distillation.md) | Memory distillation, capped index, age-stamped recall |
| [`plans/PLAN-superharness-L5.md`](plans/PLAN-superharness-L5.md) | Superharness L5: close G5c, wire dormant learning loops |
| **Infrastructure** | |
| [`windows-native-full-fix-tdd-plan.md`](windows-native-full-fix-tdd-plan.md) | Native Windows fix TDD plan |
| [`REMOVE-ALL-PROTOCOL-YAML.md`](REMOVE-ALL-PROTOCOL-YAML.md) | Remove all protocol YAML (in progress) |
| [`plans/harness-phi4mini-redesign.md`](plans/harness-phi4mini-redesign.md) | phi4-mini/Ollama harness — redesign against main |
| **Module / Feature** | |
| [`plan-effort-taxonomy-opus47-morpheme.md`](plan-effort-taxonomy-opus47-morpheme.md) | Effort taxonomy + Opus 4.7 |
| [`plan-missions-alignment.md`](plan-missions-alignment.md) | Missions alignment (Factory talk) |
| [`PLAN-superharness-plugin.md`](PLAN-superharness-plugin.md) | Superharness as a Claude Code plugin (`/shux`) |
| [`PLAN-token-cost-accounting.md`](PLAN-token-cost-accounting.md) | Per-task token/cost accounting |
| [`PROPOSAL-session-injection-discussion-dispatch.md`](PROPOSAL-session-injection-discussion-dispatch.md) | Session injection for discussion dispatch |
| **Subsystem Plans** | |
| [`plans/failure-management.md`](plans/failure-management.md) | Three-layer failure management |
| [`plans/headless-auto-dispatch.md`](plans/headless-auto-dispatch.md) | Headless-auto-dispatch strategy |
| [`plans/superharness-operator.md`](plans/superharness-operator.md) | Operator watchdog design |
| [`plans/workflow-autonomy.md`](plans/workflow-autonomy.md) | Workflow + per-project autonomy |

## 🔍 Reviews

| Doc | What |
|-----|------|
| [`senior-review-2026-05-20.md`](senior-review-2026-05-20.md) | Senior review — 11 fixes, C4-C6 decomposition |
| [`claude_superharness_review.md`](claude_superharness_review.md) | Claude review |
| [`codex_superharness_review.md`](codex_superharness_review.md) | Codex review |
| [`gemini_superharness_review.md`](gemini_superharness_review.md) | Gemini review |
| [`SKILL_GENERICITY_REVIEW.md`](SKILL_GENERICITY_REVIEW.md) | Skill genericity review (2026-05-26) |

## 🐛 Bugs

| Doc | What |
|-----|------|
| [`BUG-set-owner-inbox-cleanup.md`](BUG-set-owner-inbox-cleanup.md) | ImportError in inbox cleanup |
| [`bugs/2026-05-11_discuss_dispatch_bugs.md`](bugs/2026-05-11_discuss_dispatch_bugs.md) | Discuss dispatch bugs through v1.56.2 |
| [`bugs/2026-05-21_ai-driven-dispatch-failure.md`](bugs/2026-05-21_ai-driven-dispatch-failure.md) | Why `ai_driven` autonomy did not dispatch (morpheme project) |
| [`bugs/2026-05-21_discuss_cli_ux_bugs.md`](bugs/2026-05-21_discuss_cli_ux_bugs.md) | `shux discuss` UX and retry-alert bugs (v1.62.20) |
| [`bugs/BUG-2026-06-04-operator-orphans-pytest-swap-storm.md`](bugs/BUG-2026-06-04-operator-orphans-pytest-swap-storm.md) | Operator orphans pytest → 34 GB swap storm |
| [`bugs/BUGREPORT-discussion-consensus-single-participant.md`](bugs/BUGREPORT-discussion-consensus-single-participant.md) | Discussion consensus reached with only 1 of 3 participants |
| [`bugs/BUGREPORT-watcher-silent-death-no-recovery.md`](bugs/BUGREPORT-watcher-silent-death-no-recovery.md) | Watcher silent death — no auto-recovery (19+ hour outage) |
| [`bugs/discussion-dispatch-tier-ignored-double-failure.md`](bugs/discussion-dispatch-tier-ignored-double-failure.md) | Discussion dispatch fails twice — max tier ignored, silent failures |
| [`bugs/gemini-discussion-dispatch-silent-failure.md`](bugs/gemini-discussion-dispatch-silent-failure.md) | Gemini-CLI discussion dispatch fails silently |
| [`bugs/watcher-dies-between-sessions.md`](bugs/watcher-dies-between-sessions.md) | Watcher dies between sessions — root cause report |

## 🧾 Bulletproof / Verification Reports

Point-in-time claim-vs-reality audits. Superseded runs live in `docs/archive/`; the two most recent stand-alone reports remain active:

| Doc | What |
|-----|------|
| [`bulletproof-report-2026-06-08.md`](bulletproof-report-2026-06-08.md) | General audit, v14 |

## 📐 Specifications & References

| Doc | What |
|-----|------|
| [`specs/state-backend-interfaces.md`](specs/state-backend-interfaces.md) | State backend interfaces (authoritative) |
| [`adapter-payload-spec.md`](adapter-payload-spec.md) | Adapter payload JSON schema |
| [`adapter-models.md`](adapter-models.md) | Adapter model-to-tier mapping |
| [`pack-format.md`](pack-format.md) | shux pack archive format |
| [`MCP-MEMORY.md`](MCP-MEMORY.md) | Optional MCP memory server setup |
| [`morpheme-branch-policy.md`](morpheme-branch-policy.md) | Morpheme branch policy (retired) |

## 📎 Reports & Misc

| Doc | What |
|-----|------|
| [`REPO-MIGRATION-fork-situation.md`](REPO-MIGRATION-fork-situation.md) | Repo migration — `celstnblacc` → `artificemachine` fork situation |
| [`REPORT-process-leak-2026-05-28.md`](REPORT-process-leak-2026-05-28.md) | Process leak incident report |

---

## 📦 Archived (39 files in `docs/archive/`)

Obsolete, completed, superseded, or dated docs moved to archive. See `docs/archive/` for:
- Session handoff notes (`HANDOFF-2026-06-*.md`, `NEXT_SESSION_HANDOFF.md`, `handoff-yaml-cleanup-session-2026-05-13.md`)
- Superseded bulletproof-report runs (13 dated 2026-05-22 through 2026-05-25, superseded by the active reports above)
- A dated release checklist (`RELEASE-TODO-v1.62.15.md`)
- Completed migration/cleanup plans (SQLite migration, contract-YAML removal, module system, onboarding pipeline)
- Stale comparisons/audits/reviews (pi-hermes comparison, Dorothy comparison, drift audit, architecture review)

---

**Last updated:** 2026-07-19 | **Active docs:** 112 | **Archived:** 39
