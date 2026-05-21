# superharness — Documentation Index

> Auto-generated 2026-05-20. 61 active docs (19 archived). Run `docs-organize` skill to audit.

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
| [`DESIGN-risky-choices.md`](DESIGN-risky-choices.md) | Documented sharp edges and risky choices |
| [`ROADMAP-phases.md`](ROADMAP-phases.md) | **Master phase roadmap** (single source of truth) |
| [`IMPLEMENTATION-status.md`](IMPLEMENTATION-status.md) | Implementation status across all audits |
| [`improvement-roadmap.md`](improvement-roadmap.md) | Morpheme + superharness improvement roadmap |
| [`improvement-tdd-plans.md`](improvement-tdd-plans.md) | Improvement TDD plans per PR |

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

## 🔒 Security & Audits

| Doc | What |
|-----|------|
| [`gateway-security.md`](gateway-security.md) | Notification gateway security audit |
| [`SECURITY-autonomous-dispatch.md`](SECURITY-autonomous-dispatch.md) | Autonomous dispatch security gates |
| [`defense_layers_plan.md`](defense_layers_plan.md) | Defense layers TDD iteration plan |
| [`AUDIT-agent-harness-comparison.md`](AUDIT-agent-harness-comparison.md) | Browser-harness vs Hermes vs superharness |
| [`AUDIT-claude-mem-adaptation.md`](AUDIT-claude-mem-adaptation.md) | Claude-mem adaptation audit |
| [`AUDIT-paperclip-gap-analysis.md`](AUDIT-paperclip-gap-analysis.md) | Superharness vs Paperclip gap analysis |
| [`AUDIT-pi-hermes-adaptation.md`](AUDIT-pi-hermes-adaptation.md) | **Pi-Mono + Hermes adaptation audit** (ground truth) |
| [`yaml-inventory.md`](yaml-inventory.md) | YAML file inventory post phase-4 cleanup |

## 📋 Plans (Active)

| Doc | What |
|-----|------|
| **Hermes / Pi-Mono** | |
| [`PLAN-hermes-features-to-steal.md`](PLAN-hermes-features-to-steal.md) | Shipped + gaps + 3-phase priority plan |
| [`hermes-integration-tdd-plan.md`](hermes-integration-tdd-plan.md) | Hermes integration TDD iterations |
| **Paperclip** | |
| [`PLAN-absorb-paperclip-features.md`](PLAN-absorb-paperclip-features.md) | Absorb paperclip features plan |
| **Claude-Mem** | |
| [`PLAN-claude-mem-integration.md`](PLAN-claude-mem-integration.md) | Claude-mem integration iteration plan |
| **Ralph** | |
| [`PLAN-ralph-extraction.md`](PLAN-ralph-extraction.md) | Ralph loops extraction plan |
| **Auto-Mode** | |
| [`auto-mode-gap-v2.md`](auto-mode-gap-v2.md) | Auto-mode gap analysis v2 |
| [`auto-mode-gap-plan.md`](auto-mode-gap-plan.md) | Auto-mode TDD implementation plan |
| **Task Lifecycle** | |
| [`plan-subtask-resolution-gate.md`](plan-subtask-resolution-gate.md) | Subtask resolution gate plan |
| [`design-task-lifecycle-ship.md`](design-task-lifecycle-ship.md) | Ship step in task lifecycle |
| [`plan-task-workflow-v2.md`](plan-task-workflow-v2.md) | Task workflow v2 implementation |
| **Infrastructure** | |
| [`PLAN-portable-adapter-paths.md`](PLAN-portable-adapter-paths.md) | Portable adapter paths |
| [`PLAN-portable-paths-cleanup.md`](PLAN-portable-paths-cleanup.md) | Portable paths cleanup |
| [`PLAN-protocol-evolution.md`](PLAN-protocol-evolution.md) | Protocol friction reduction |
| [`PLAN-wizard-gateway-adaptation.md`](PLAN-wizard-gateway-adaptation.md) | Wizard + gateway adaptation |
| [`windows-native-full-fix-tdd-plan.md`](windows-native-full-fix-tdd-plan.md) | Native Windows fix TDD plan |
| [`REMOVE-ALL-PROTOCOL-YAML.md`](REMOVE-ALL-PROTOCOL-YAML.md) | Remove all protocol YAML (in progress) |
| **Module / Feature** | |
| [`plan-effort-taxonomy-opus47-morpheme.md`](plan-effort-taxonomy-opus47-morpheme.md) | Effort taxonomy + Opus 4.7 |
| [`plan-missions-alignment.md`](plan-missions-alignment.md) | Missions alignment (Factory talk) |
| **Subsystem Plans** | |
| [`plans/failure-management.md`](plans/failure-management.md) | Three-layer failure management |
| [`plans/headless-auto-dispatch.md`](plans/headless-auto-dispatch.md) | Headless auto-dispatch strategy |
| [`plans/superharness-operator.md`](plans/superharness-operator.md) | Operator watchdog design |
| [`plans/workflow-autonomy.md`](plans/workflow-autonomy.md) | Workflow + per-project autonomy |

## 🔍 Reviews

| Doc | What |
|-----|------|
| [`senior-review-2026-05-20.md`](senior-review-2026-05-20.md) | Senior review — 11 fixes, C4-C6 decomposition |
| [`claude_superharness_review.md`](claude_superharness_review.md) | Claude review |
| [`codex_superharness_review.md`](codex_superharness_review.md) | Codex review |
| [`gemini_superharness_review.md`](gemini_superharness_review.md) | Gemini review |

## 🐛 Bugs

| Doc | What |
|-----|------|
| [`BUG-set-owner-inbox-cleanup.md`](BUG-set-owner-inbox-cleanup.md) | ImportError in inbox cleanup |
| [`bugs/2026-05-11_discuss_dispatch_bugs.md`](bugs/2026-05-11_discuss_dispatch_bugs.md) | Discuss dispatch bugs through v1.56.2 |

## 📐 Specifications & References

| Doc | What |
|-----|------|
| [`specs/state-backend-interfaces.md`](specs/state-backend-interfaces.md) | State backend interfaces (authoritative) |
| [`adapter-payload-spec.md`](adapter-payload-spec.md) | Adapter payload JSON schema |
| [`adapter-models.md`](adapter-models.md) | Adapter model-to-tier mapping |
| [`pack-format.md`](pack-format.md) | shux pack archive format |
| [`MCP-MEMORY.md`](MCP-MEMORY.md) | Optional MCP memory server setup |
| [`morpheme-branch-policy.md`](morpheme-branch-policy.md) | Morpheme branch policy (retired) |

---

## 📦 Archived (19 files in `docs/archive/`)

Obsolete, completed, or superseded docs moved to archive. See `docs/archive/` for:
- 3 session handoff notes
- 8 obsolete plans (completed features)
- 8 stale comparisons/audits/reviews

---

**Last updated:** 2026-05-20 | **Active docs:** 61 | **Archived:** 19
