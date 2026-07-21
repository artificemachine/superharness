# Task & Discussion Tier/Effort Classification

Both tasks and discussions are auto-classified via the same multi-agent classifier chain in `engine/model_router.py`. Tasks are classified at `auto_dispatch` time; discussions are classified at creation time (`discuss.py`). Same function (`classify_task()`), same prompt, same 4-agent chain.

## Classifier chain

Four agents tried in order, each with their mini-tier model. First to respond wins. 5s timeout each.

| Priority | Agent | Mini model | Cost |
|---|---|---|---|
| 1 | claude-code | haiku | ~$0.0002 |
| 2 | gemini-cli | gemini-2.5-flash | ~$0.0001 |
| 3 | opencode | deepseek-chat | ~$0.00005 |
| 4 | codex-cli | gpt-5.1-codex-mini | ~$0.0001 |

All four down → falls back to `standard` tier, `medium` effort.

## Classification examples

### Discussions

| `shux discuss "..."` | Output | All agents dispatched with |
|---|---|---|
| "rewrite ML pipeline with Bayesian inference" | `max high` | Max models, 60-min timeout |
| "rename config key from foo to bar" | `standard low` | Standard models, 15-min timeout |
| "add exchange adapter for Binance" | `standard medium` | Standard models, 30-min timeout |
| "migrate PostgreSQL schema for order history" | `max medium` | Max models, 30-min timeout |
| "should we switch from pip to uv" | `standard low` | Standard models, 15-min timeout |

### Tasks

| `shux delegate "..."` | Output | Agent + model |
|---|---|---|
| "fix typo in README" | `mini low` | codex-cli / gpt-5.1-codex-mini |
| "add unit tests for order matching" | `standard medium` | claude-code / sonnet-4-6 |
| "design rate-limiting for WebSocket feed" | `max high` | claude-code / opus-4-7 |
| "update changelog for v1.62" | `mini low` | codex-cli / gpt-5.1-codex-mini |

## Tier → model mapping

The tier is resolved to agent-specific models via `resolve_model()`:

| Tier | claude-code | gemini-cli | opencode | codex-cli |
|---|---|---|---|---|
| mini | haiku | 2.5-flash | deepseek-chat | gpt-5.1-codex-mini |
| standard | sonnet-4-6 | 2.5-pro | deepseek-v4-pro | gpt-5.3-codex |
| max | opus-4-7 | 3.1-pro-preview | deepseek-v4-pro | gpt-5.4 |

## Override options

```bash
# Per-session, per-agent (env var)
SUPERHARNESS_CLAUDE_MODEL=claude-opus-4-7 shux discuss "topic"

# All agents via profile config (coming soon)
shux config set discussion_model_tier max
```

## Files involved

| File | Role |
|---|---|
| `engine/model_router.py` | `classify_task()` — 4-agent classifier chain (shared) |
| `engine/models.yaml` | Tier → model mapping table (shared) |
| `commands/auto_dispatch.py` | Classifies tasks at dispatch time, enqueues with resolved model |
| `commands/discuss.py` | Classifies discussion topic at creation, writes tier+effort to round-1 task |
| `commands/discussion_dispatch.py` | Propagates tier+effort from round-1 to later rounds |
| `commands/inbox_dispatch.py` | Reads task's model_tier, resolves model per agent, injects `--model` (all agents) |
| `scripts/delegate-to-gemini.sh` | Forwards `--model` to gemini CLI |
