# Concept: SDK vs CLI Dispatch

Superharness supports two distinct dispatch paths for agent execution. Understanding the difference is critical for maintaining engine integrity and preventing "model mismatch" errors.

## 1. SDK Dispatch (Claude Code only)
When the target agent is `claude-code`, the engine prefers using the **Claude Agent SDK** (`claude_agent_sdk` Python library).

### Why Claude uses the SDK:
*   **Headless Autonomy**: The SDK allows setting `permission_mode: "bypassPermissions"`. This is essential for background watchers where no human is present to answer `y/n` terminal prompts.
*   **Session Forking (Memory)**: The SDK runner can fork the most recent successful session. This provides a "warm start" where the agent inherits project context without re-scanning the entire codebase.
*   **Structured Usage**: Returns exact input/output token counts for precise cost tracking in the dashboard.
*   **Speed**: Faster startup time compared to launching a full pseudo-terminal (PTY) shell.

## 2. CLI Dispatch (Gemini, Codex, and Claude Fallback)
For all other agents, or if the SDK is unavailable, the engine uses **CLI Dispatch**.

### How it works:
1.  The dispatcher identifies the target agent (e.g., `gemini-cli`).
2.  It resolves the launcher script via the `adapter_registry` (e.g., `delegate-to-gemini.sh`).
3.  It spawns the script in a clean PTY environment.

## 3. The "use_sdk" Safety Guard
A critical engine constraint (implemented in `v1.29.3`) ensures that **SDK mode is never used for non-Claude agents**.

### The logic:
```python
# Only claude-code supports the SDK runner
supports_sdk = (target == "claude-code")
use_sdk = (sdk_available() and supports_sdk)
```

### Why this guard exists:
If a non-Claude agent (like Gemini) is forced into the SDK path, the engine will attempt to use Claude-specific models (like `sonnet`) and parameters. This results in `400 Bad Request` errors because Gemini does not understand the Claude protocol.

## Summary Matrix

| Agent | Preferred Path | Fallback Path | Rationale |
|-------|---------------|---------------|-----------|
| `claude-code` | SDK | CLI | Autonomy & Memory |
| `gemini-cli` | CLI | - | Native Gemini Protocol |
| `codex-cli` | CLI | - | Native OpenAI Protocol |
