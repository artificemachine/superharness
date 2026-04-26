# Unified Quota & Health Engine

This document describes the multi-layered budget and health system in Superharness, designed to prevent silent token burn, enforce runtime quotas, and ensure agent availability before dispatch.

## Core Concepts

Superharness enforces a "Human-in-the-Loop" validation gate when a task finishes and moves to the review phase. This gate evaluates four dimensions of agent readiness:

1.  **Local USD Budget**: Daily spend limits tracked in `benchmark.jsonl`.
2.  **Runtime Quota**: Daily active duration limits (e.g., "5 hours/day quota").
3.  **External Provider Quota**: Real-time utilization signals from Anthropic, Google, or OpenAI.
4.  **Endpoint Reachability**: Connectivity checks for local models (Ollama/vLLM).

## Configuration

Budgets and quotas are defined in `.superharness/profile.yaml` under the `budget` key. It supports global defaults and per-agent overrides.

```yaml
budget:
  daily_limit: 5.00    # Global USD limit
  daily_hours: 5.0     # Global runtime quota (hours)
  strict: false        # Warn only (true = hard block at 100%)
  agents:
    claude-code:
      daily_limit: 10.00
      daily_hours: 2.0
    codex-cli:
      daily_limit: 5.00
```

## Health Dimensions

### 1. Runtime Quota (Daily Hours)
Calculated by summing the `duration_seconds` of all tasks performed by an agent today. If an agent has a `daily_hours: 5.0` quota and has already worked for 5 hours, it will be marked as **BLOCKED** or **WARN** depending on the `strict` setting.

### 2. External Provider Quotas
Superharness monitors `/tmp/*.usage-cache.json` files to surface real-time usage from AI providers. These files are typically populated by status-line scripts or OAuth helpers.

*   **Claude Code**: `/tmp/claude-usage-cache.json`
*   **Gemini CLI**: `/tmp/gemini-usage-cache.json`
*   **Codex CLI**: `/tmp/codex-usage-cache.json`

If the `utilization` field in these JSON files reaches `1.0` (100%), the agent is automatically **BLOCKED** in the Superharness UI, regardless of local budget status.

### 3. Local Model Reachability
For agents like `ollama` or `vllm` that do not have token quotas, Superharness performs a real-time reachability check (HTTP HEAD) before validation.
*   **Ollama**: `localhost:11434`
*   **vLLM**: `localhost:8000`

If the endpoint is down, the agent is marked as **OFFLINE** and dispatch is blocked.

## Dashboard Validation Flow

When a task reaches `report_ready`, the **"Validate Reviewers"** dialog appears. This is your primary console for quota management:

- **USD Metrics**: Displays `$Used / $Limit` for each agent.
- **Runtime Metrics**: Displays `HoursUsed / HourLimit` (e.g., `1.5h/5.0h`).
- **External Signals**: Surfaces "Real Quota: X% used" from providers.
- **Smart Selection**: Blocked or Offline agents are automatically dimmed and unchecked.

## CLI Enforcement

The `check_budget` engine is integrated into `shux delegate`. If you attempt to dispatch to a blocked agent via the terminal:
- It will print a **⛔ BLOCKED** message with the reason (e.g., `External quota 100% EXHAUSTED`).
- It will exit with an error unless the `--force` flag is provided.
