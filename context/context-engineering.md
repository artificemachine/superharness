# Context Engineering — DEPRECATED

**This file is no longer maintained.**

Claude Code now handles context engineering internally (Auto Memory, Session Memory, KV-cache optimization). superharness no longer needs to document these patterns.

For cross-agent context concerns, see:
- `agents/protocol.md` — how agents share context via contracts/handoffs
- `identity/core.md` — the minimal identity kernel injected at session start

The original content was based on Anthropic's 2025 paper "Effective Context Engineering for AI Agents" and covered Write/Select/Compress/Isolate operations, the 60% utilization rule, token budgets, and cache-friendly patterns. This is now handled natively by the tools themselves.
