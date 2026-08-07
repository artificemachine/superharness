# Langfuse observability

Langfuse is an optional dispatch-observability backend. It complements the
Superharness dashboard; SQLite and `benchmark.jsonl` remain authoritative.

## Install

Install the released package with `pip install 'superharness[observability]'`.
For repository development, use a repository-local virtual environment only.

## Configure

Add these entries to `$HOME/.config/superharness/credentials.env`:

```text
SUPERHARNESS_LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=your-public-key-here
LANGFUSE_SECRET_KEY=CHANGE_ME
LANGFUSE_BASE_URL=https://langfuse-ops.gitsilence.net
LANGFUSE_TRACING_ENVIRONMENT=production
```

Run `chmod 600 $HOME/.config/superharness/credentials.env`. Environment
variables are fallback values; an entry in this file takes precedence. See
[gateway security](gateway-security.md) for the machine credential model.

With a valid enabled `LANGFUSE_BASE_URL`, the dashboard shows a configured
**Langfuse ↗** link; otherwise it stays hidden. Its original compact dimensions
(4px by 12px padding, 12px text, 6px radius) use an orange three-second pulse,
disabled by `prefers-reduced-motion`. Themes are Dark, Light, and Monokai;
Monokai is the default unless browser `localStorage` contains a valid selection.

## Privacy boundary

Exported fields are pseudonymous project/task IDs, agent, outcome, duration,
cost, model, parallel-slot data, timestamp, and Superharness version.
Prompts, responses, task text, raw task IDs, paths, logs, and secrets are never exported.

## Verify

1. Run `shux doctor --project .` for an offline configuration check.
2. With network approval, run `shux doctor --langfuse-auth --project .`.
3. With event-emission approval, run:
   `python -c 'from superharness.engine.langfuse_telemetry import emit_dispatch_event as e; print(e(".", {"task_id":"synthetic-smoke","agent":"operator","outcome":"done","duration_seconds":0,"cost_usd":0}))'`
4. Confirm one `superharness.dispatch.completed` event in the Langfuse UI.

If the SDK is missing, reinstall the optional extra. If authentication fails,
check the URL and project keys without printing them. If the host is
unreachable, dispatch continues locally and the export is skipped.
