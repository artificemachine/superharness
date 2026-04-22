# Architectural Audit: AI Harness & Agent Comparison
**Date:** 2026-04-21
**Scope:** `browser-harness` (Remote) vs `hermes-agent` (Reference) vs `superharness` (Project Baseline)

## Executive Summary
This audit evaluates the current AI stack against emerging patterns in the agentic ecosystem. While `hermes-agent` provides a comprehensive framework, it is redundant given the existing integration of **Claude Code**, **osm MCP**, and **superharness**. However, `browser-harness` introduces a "Self-Healing" pattern that is highly complementary to the orchestration-heavy approach of `superharness`.

---

## 1. Technical Matrix

| Dimension | browser-harness | hermes-agent | superharness |
| :--- | :--- | :--- | :--- |
| **Architectural Layer** | Execution (Browser) | Platform (Personal AI) | Orchestration (Governance) |
| **Primary Goal** | Functional Extensibility | Personal Identity & Memory | Task Lifecycle & Multi-agent Sync |
| **Correction Logic** | **Self-Healing**: Mid-task code mutation of `helpers.py`. | **Skill Distillation**: Post-task creation of Markdown skills. | **Remediation**: In-context fix hints via failure classifiers. |
| **Execution Sandbox** | Local/Cloud CDP Bridge | Docker / SSH / Modal | Git Worktrees (Isolated FS) |
| **Persistence Model** | Ephemeral (Tool-focused) | Deep (SQLite + FTS5) | Strategic (Handoffs + Ledger) |

---

## 2. Key Differentiation

### browser-harness: Tactical Flexibility
The core innovation in `browser-harness` is the **Agent-Editable Helper Pattern**. By keeping browser tools in a single, modifiable `helpers.py`, the agent can autonomously implement missing functionality (e.g., adding a specific file-upload handler) without human intervention.
*   *Status:* Recommended for integration as a **Skill** within the superharness ecosystem.

### hermes-agent: Contextual Depth
`hermes-agent` focuses on the "agent-to-user" relationship, featuring a learning loop that builds a model of the user. It excels at multi-channel communication (Telegram/Discord) and automated session summarization.
*   *Status:* **Redundant.** The existing stack (Claude Code + shux) already handles these capabilities with less architectural overhead.

### superharness: Governance & Reliability
`superharness` provides the "Command and Control" layer. Its focus on **Failure Pattern Matching** ensures that when an agent fails (e.g., a Python `ImportError` or a `GitConflict`), the root cause is classified and fixed in the next dispatch.
*   *Status:* **Baseline.** Remains the primary orchestrator for complex, multi-step engineering tasks.

---

## 3. Security & Sandboxing Analysis

| Feature | OpenClaw + NemoClaw | Hermes Agent |
| :--- | :--- | :--- |
| **Isolation Model** | **Hardened/External**: Uses NemoClaw as a physical/VM sandbox boundary. | **Optional/Internal**: Relies on Docker/SSH backends or local execution. |
| **Command Approval** | Local Terminal (Prompt-based). | Terminal + **Remote** (Mobile approval via Telegram). |
| **Safety Logic** | **External Governance**: Superharness enforces task contracts and ledger limits. | **Internal Guardrails**: Regex-based blocking and path deny-lists in `approval.py`. |
| **Attack Surface** | Minimal (Local-only). | Moderate (Exposes messaging APIs for remote control). |

### Security Observations
*   **Hermes Agent** attempts to solve security "from the inside" using path-blocking and environment stripping. While convenient, this is structurally weaker than the **NemoClaw** "outside-in" sandbox approach.
*   The **Messaging Gateway** in Hermes introduces a new risk vector: mobile access to the agent's shell. While secured by "User Pairing," it expands the threat model beyond the local machine.

---

## 4. Synergy & Next Steps

### Proposed Integration: The "Mutation" Skill
Instead of viewing `browser-harness` as a separate agent, its "Self-Healing" logic should be adapted into a `superharness` Skill.
1.  **Skill Registry:** Register `helpers.py` as a "mutable asset" in the task context.
2.  **Failure Trigger:** If a task fails with a "Missing Feature" pattern, `superharness` triggers a subtask to mutate the helper code.
3.  **Validation:** Use `shux verify` to ensure the mutation doesn't break existing tests before closing the task.

### Recommendation & Advice
*   **Retain Baseline:** Keep `superharness` + `NemoClaw` as the primary engineering environment. The external governance and hardened isolation are superior for high-stakes repository work.
*   **Adopt Remote Approval:** If mobile control is required, consider cherry-picking the Telegram/Discord adapter patterns from `hermes-agent/gateway` into your existing bridge, rather than switching to the Hermes framework.
*   **Implement "Self-Healing":** Prioritize the `helpers.py` mutation pattern from `browser-harness` to increase agent autonomy within the existing safe sandbox.
*   **Archive Reference:** Keep `hermes-agent` as a code reference only. Do not deploy its gateway in a production environment without rigorous security hardening of the messaging backend.
*   **Migration Guide:** Follow the [Migration Guide](../../openclaw-deploy/docs/GUIDE-migration-openclaw-to-hermes.md) to upgrade the NemoClaw resident engine from OpenClaw to Hermes.
