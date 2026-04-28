# Hermes-Agent Cherry-Pick Audit

> Date: 2026-04-28
> Source: `/Users/airm2max/DevOpsSec/hermes-agent`
> Context: `docs/AUDIT-agent-harness-comparison.md` line 65

## Executive Summary

`hermes-agent` has 10 patterns worth cherry-picking for superharness. None require deploying hermes-agent itself — they are self-contained code patterns that can be adapted into superharness modules.

---

## Must-Pick (high impact, low effort)

### 1. Tool Registry Pattern

**Source:** `tools/registry.py` (237 lines)

Every tool self-registers at module import time via `registry.register()`. One central singleton queried by `model_tools.py` to build schemas and dispatch calls. No manual schema maintenance, no parallel data structures.

```python
# Pattern (conceptual)
class ToolRegistry:
    _tools: dict[str, ToolDef] = {}

    def register(self, name, fn, schema, category, requires_env=None):
        self._tools[name] = ToolDef(name, fn, schema, category, requires_env)

# Each tool file:
registry = get_registry()
registry.register("shux_task", cmd_task, task_schema, "contract")

# Dispatch:
tool = registry.get("shux_task")
tool.fn(**tool.parse_args(user_input))
```

**Superharness benefit:** Replace scattered `_cmd()` factory calls in `cli.py` with centralized registry. Each command module self-registers. Adding a command becomes: create file, call `register()`, done.

### 2. Approval State With Smart Approvals

**Source:** `tools/approval.py:96-193, 280-339`

Thread-safe per-session approval tracking with scoped persistence:

- `_session_approved` — approved for current session only
- `_permanent_approved` — persistent allowlist in config
- Legacy key aliasing — old pattern keys survive config changes
- Smart Approvals — auxiliary LLM evaluates command risk before requiring user approval

**Superharness benefit:** Fits our peer-approval gap (Gap A from `auto-mode-gap-v2.md`). When a plan_proposed task needs approval, the system could:
1. Run plan_validator checks (done)
2. Use Smart Approvals to auto-approve low-risk tasks
3. Escalate high-risk tasks to peer agent or operator

---

## Should-Pick (medium impact)

### 3. Event Hook System

**Source:** `gateway/hooks.py` (153 lines)

Users drop `HOOK.yaml` + `handler.py` into a hooks directory. Hooks fire on lifecycle events. Errors caught and logged, never block main pipeline.

```yaml
# HOOK.yaml
name: notify-telegram
events: [task:completed, task:failed]
```

```python
# handler.py
def on_task_completed(event):
    send_telegram(f"Task {event.task_id} done")
```

**Superharness benefit:** Operators get notified on task completion/failure without polling the dashboard. Hooks could trigger: Slack messages, desktop notifications, webhook calls, auto-deploy pipelines.

### 4. Session Auto-Expiry With Memory Flush

**Source:** `gateway/run.py:1033-1069`

Background task checks session expiry every 5 minutes. Before a session expires, it proactively flushes memories to disk (not after expiry when data is already lost).

**Superharness benefit:** Our lifecycle reconciler handles timeouts reactively (task times out → archive). The hermes pattern adds proactive flushing: before the 180m in_progress timeout, flush any partial work to handoffs so nothing is lost.

### 5. Git Worktree Isolation

**Source:** `cli.py:506-748`

Creates isolated git worktrees with:
- `.worktreeinclude` — gitignored files allowed in worktree (e.g., `.env`)
- Stale pruning on startup (>24h, no uncommitted changes)
- Clean removal on exit if no changes
- Auto-stash before checkout

**Superharness benefit:** superharness already uses worktrees for dispatch, but the hermes implementation adds stale pruning, include files, and clean removal. Directly applicable to `engine/worktree_ops.py`.

---

## Nice-to-Have (lower priority)

### 6. Slash Command Registry

**Source:** `hermes_cli/commands.py`

One `COMMAND_REGISTRY` list auto-derives: CLI dispatch, gateway dispatch, bot menus, autocomplete, help text. Adding a command = one entry in one file.

### 7. Subagent Credential Routing

**Source:** `tools/delegate_tool.py:565-651`

Subagents can use different providers/models than the parent. `_resolve_delegation_credentials()` routes credentials per-model. Configurable tool restriction per subagent.

### 8. Gateway Streaming Consumer

**Source:** `gateway/stream_consumer.py` (202 lines)

Thread-safe bridge from sync agent stream callbacks to async platform message editing. Queues token deltas, progressively edits a single platform message.

### 9. Context Compressor

**Source:** `agent/context_compressor.py` (658 lines)

Auto-triggers at 50% of model's context limit. Structured handoff summary with Goal/Progress/Decisions/Files/Next Steps. Protects most recent ~20K tokens. Orphan tool pair sanitization.

### 10. Skills Manifest Sync

**Source:** `tools/skills_sync.py` (287 lines)

Manifest-based seeding with hash-based change detection. Never overwrites user-modified skills. Atomic manifest writes with tempfile+replace.

---

## What NOT to pick

| Pattern | Why not |
|---------|---------|
| Telegram/Discord platform adapters | hermes-agent uses `python-telegram-bot` library directly. superharness should use the hook system instead — platform integration via hooks, not embedded adapters. |
| Full gateway runner | Redundant with superharness operator + daemon. |
| Memory tool (MEMORY.md + USER.md) | Already handled by superharness handoffs + ledger. |
| Voice channel pipeline | Not in superharness scope. |
| Skin/theme engine | Cosmetic, not architectural. |
