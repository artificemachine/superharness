# Design Plan: Reducing Protocol Friction
**Date:** 2026-04-21
**Goal:** Transition from "Agent-as-Participant" (manual file management) to "Agent-as-Substrate" (automated governance).

## The Friction Problem
The current `superharness` protocol requires agents to manually read and update YAML/Handoff files. This creates three failure modes:
1.  **Context Exhaustion:** Large YAML files consume token budget.
2.  **Formatting Brittleness:** LLMs occasionally break YAML syntax (missing colons, indentation).
3.  **Compliance Fatigue:** Agents forget to update the ledger/handoff at the end of a session.

---

## 1. Zero-Touch Strategies

### A. Shadow Ledger (Middleware Interception)
Wrap the agent's shell in a `shux-proxy` that intercepts terminal output.
*   **Mechanism:** Use regex to detect "Task Completed" or "Decision Made" events in real-time.
*   **Benefit:** The agent works naturally; the environment extracts the state automatically.

### B. Auto-Injected Instructions (Gemini/Claude/Codex Hooks)
Leverage native platform files (`CLAUDE.md`, `GEMINI.md`, `AGENTS.md`).
*   **Mechanism:** `superharness` becomes the "Source of Truth" that generates these instruction files on every `shux dispatch`.
*   **Expansion:** Support **Claude Code**, **Gemini CLI**, and **Codex** hooks simultaneously.
*   **Benefit:** No need to "remind" the agent of the protocol; it is hard-coded into the files they read first.

### C. Git-Native State
Leverage Git metadata (Notes/Commits) instead of a standalone `handoff/` folder.
*   **Mechanism:** Use a `post-commit` hook to parse commit messages and automatically transition task statuses in the contract.
*   **Benefit:** Aligns with standard engineering workflows.

---

## 2. Structural Improvements

### D. Multi-Agent & Local Model Support
Expand `superharness` to support a broader range of execution environments.
*   **Current Owners:** `claude-code`, `codex`.
*   **Immediate Addition:** `gemini` (native support for Gemini CLI).
*   **Local Tier:** Integrate **Ollama** and **vLLM** as providers for local, air-gapped engineering.
*   **Implementation:** Update `adapter_registry.py` and `model_router.py` to handle local endpoint routing and hardware-specific constraints (VRAM, context windows).

### E. Markdown-First Contracts
Shift the primary agent-facing state from YAML to structured Markdown.
*   **Logic:** LLMs are significantly more robust at appending to Markdown lists/tables than editing nested YAML.
*   **Implementation:** Use a background "Sync Engine" (Morpheme) to maintain a high-speed JSON/YAML cache for CLI tools while the agent interacts with `.superharness/CONTRACT.md`.

### F. Superharness MCP Server (The "No-File" Path)
... (existing pros/cons) ...
*   **Summary Advice:** Adopt a **Hybrid Approach**. Use MCP for agent *writes* (integrity) and auto-injected Markdown (`CONTRACT.md`) for agent *reads* (visibility/native context).

### G. Morpheme Integration & Architectural Boundaries
To maintain a clean stack, we distinguish between the **State Producer** (Superharness) and the **State Consumer** (Morpheme).
*   **Decoupling via MCP:** Morpheme will transition from "File-Watcher" to "MCP Client." Instead of parsing YAML directly, it consumes the **v1.1 adapter-payload** via the MCP server.
*   **The "Mirroring" Rule:** The MCP server must remain "Stateless" relative to the repository. Every write request from an agent or UI must result in an immediate commit to `contract.yaml`.
*   **Local Model Telemetry:** Compatibility with **Ollama/vLLM** will be handled by extending the v1.1 schema with optional hardware metrics. Morpheme will "fail gracefully" (hide UI elements) if these metrics are missing.
*   **Result:** Morpheme becomes a "Plug-and-Play" dashboard that can visualize any project exposing a Superharness MCP endpoint, regardless of the underlying storage format.

---

## 3. Implementation Roadmap

### Phase 1: Markdown Synchronization
*   [ ] Build a bidirectional bridge between `contract.yaml` and a human/agent-readable `CONTRACT.md`.
*   [ ] Update `shux hygiene` to prefer Markdown for conflict resolution.

### Phase 2: MCP Integration
*   [ ] Implement a `superharness-mcp` server that exposes the `contract.yaml` state as a set of MCP tools.
*   [ ] Update `shux delegate` to automatically announce the MCP server to the child agent.

### Phase 3: The Shadow Proxy
*   [ ] Pilot a terminal wrapper that monitors for "Decision" patterns and appends them to the ledger without agent intervention.
