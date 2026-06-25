# Autonomous Dispatch — Security Posture

> Companion to `SECURITY.md`. Where `SECURITY.md` covers the dangerous CLI bypass flags, this doc covers the **gate model**: which lifecycle states have operator checkpoints, which do not, and what that means for projects configuring auto-dispatch.

---

## TL;DR

Superharness has two designed paths through which a task can move from prompt to filesystem **without operator interaction**:

1. `round-*` task ids skip plan-only at enqueue (`commands/auto_dispatch.py`)
2. Claude Code SDK warm-start dispatch bypasses per-tool permission prompts (`adapters/claude-code/`)

In both paths, **the target agent's static policy (allowlist/denylist/sandbox config) is the operative gate** — not the interactive UI prompts an operator would see in a manual session. Verify per-agent policy before enabling auto-dispatch on a new project.

This is not a bug. The bypasses exist for legitimate reasons (discussion rounds need rapid back-and-forth; warm-start eliminates approval ceremony for trusted contracts). The risk is that **someone configuring a new project may not realize which gates are still active**.

---

## The gate model

### Lifecycle states and who advances them

| Transition | Driven by | Notes |
|---|---|---|
| `todo` → enqueued | `shux delegate` or `auto-dispatch` | Operator action OR autonomous scan of stale todos |
| enqueued → `in_progress` | Watcher picks up inbox item, launches agent | Automatic once enqueued |
| `in_progress` → `plan_proposed` | Agent writes plan handoff | Agent action |
| `plan_proposed` → `plan_approved` | **Operator** | No lifecycle rule auto-approves plans |
| `plan_approved` → `in_progress` | Agent resumes work | Agent action |
| `in_progress` → `report_ready` | Agent writes report handoff | Agent action |
| `report_ready` → `review_*` | Operator or auto-route | Auto-mode reverts stale reviews back to `report_ready` |
| `review_passed` → `done` | Operator runs `shux close` | Operator action |

**The `plan_proposed → plan_approved` transition is the primary human checkpoint.** It has no auto-approve rule in `engine/lifecycle_rules.py`.

### What `engine/lifecycle_rules.py` actually does

The lifecycle reconciler only handles **stale-state cleanup**:

| Rule | Timeout | Action |
|---|---|---|
| `todo` | 2h | archive |
| `in_progress` | 3h | archive |
| `report_ready` | 24h | archive |
| `review_requested` | 2h | revert to `report_ready` |
| `waiting_input` | 8h | fail |
| `paused` | 30m | fail (unless `reason` set) |
| `stopped` | 7d | archive |
| `deadline` exceeded | — | fail |

Every rule's `on_timeout` is one of `fail | archive | revert`. **There is no `approve` action.** The reconciler is the janitor (clean up stale items, re-route stuck reviews), not the manager (drive forward progress).

---

## Bypass 1 — `round-*` tasks skip plan-only

### Where

`src/superharness/commands/auto_dispatch.py`:

```python
def _enqueue(project_dir, task_id, agent, priority=2, plan_only=True, workflow="implementation"):
    # Non-implementation workflows (review, note, quick) have no planning phase
    if workflow != "implementation":
        plan_only = False
    # Discussion round tasks bypass plan-only when the profile flag allows it (default: True)
    if ("/round-" in str(task_id) or "round-" in str(task_id)) and _read_round_skip_flag(project_dir):
        plan_only = False
```

### Why

Discussion rounds are short-form agent-to-agent exchanges where waiting for operator plan-approval between every round would break the conversation. The design intent is correct.

### What it means for security

For any task id matching `*round-*` or `*/round-*`:
- The agent goes directly from `todo` to execution
- No `plan_proposed` state is written
- No operator approval is solicited
- The target agent's static policy is the **only** filter between the task description and the agent's tool calls

### Mitigations

- **Configurable opt-out via `profile.yaml`** (implemented):
  ```yaml
  round_tasks_skip_plan_approval: false  # require operator approval before each discussion round
  ```
  Default is `true`. Security-sensitive projects can set this to `false` to force plan-approval even for rounds, at the cost of conversational latency. Read by `_read_round_skip_flag()` in `commands/auto_dispatch.py`.
- **Naming convention enforcement**: `round-*` is a security-relevant prefix. Document this clearly when onboarding new projects — see `shux onboard` output.
- **Allowlist per project**: restrict which task templates may use `round-*` ids via per-project policy.

---

## Bypass 2 — Agent SDK warm-start skips per-tool prompts

### Where

`superharness/CLAUDE.md`:

> *"Claude Code uses the Claude Agent SDK (Python) for autonomous dispatch. This allows bypassing permission prompts and inheriting session context (warm-start)."*

Implementation in `adapters/claude-code/`.

### Why

Unattended dispatch can't sit waiting for an interactive "approve this Bash call" UI prompt — there's no operator at the keyboard. The SDK warm-start runs the agent against the policy file without surfacing per-call prompts.

### What it means for security

For SDK-dispatched tasks (which is the default for non-interactive runs):
- `~/.claude/settings.json` `permissions.allow` and `permissions.deny` still apply
- PreToolUse hooks still run
- **Per-tool interactive prompts are gone** — the "click to approve" gate that a watching operator would use does not appear

This means: if a Bash command matches the allowlist, it runs. If it matches the denylist, it's blocked. If it matches neither (would normally prompt the operator), behavior depends on `defaultMode` and `skipDangerousModePermissionPrompt`. A misconfigured project may auto-run commands that would have prompted in interactive mode.

### Mitigations to consider

- **Document this clearly in the auto-dispatch onboarding flow** — `shux onboard` could surface a warning: "Before enabling auto-dispatch for this project, run `shux check-policy` to verify your agent denylists are configured."
- **Add a `shux check-policy` command** that audits the target agent's config:
  - Claude Code: read `~/.claude/settings.json`, report denylist coverage
  - Codex: report `sandbox` and `approval_policy` values
  - Gemini: report `approvalMode` and excluded tools
  - opencode: report `permission.bash` value
- **Pre-flight check before first auto-dispatch run**: refuse to enqueue if the target agent's denylist is empty or weaker than a baseline.

---

## Before enabling auto-dispatch — operator checklist

Apply this to every project before turning on the watcher or running `shux schedule`:

### Claude Code
- [ ] `~/.claude/settings.json` `permissions.deny` covers: `rm -rf`, `sudo`, `dd if=*of=/dev/`, `mkfs.*`, `chmod 777`, `curl *| sh`, `kubectl delete`, `docker volume rm`, `git push --force`, your infra-specific destructive verbs (e.g. `proxmox-shell pct destroy`, `gcloud * delete`, `aws * rm`)
- [ ] `permissions.allow` does not contain catch-all patterns like `Bash(rm :*)`, `Bash(curl :*)`, `Bash(bash :*)`
- [ ] `defaultMode: "plan"` and `skipDangerousModePermissionPrompt: false` (or accept that plan-mode prompts are bypassed)
- [ ] PreToolUse Bash hook present (e.g. compound-operator rejector to block `npm test && rm -rf prod`)

### Codex CLI
- [ ] `~/.codex/config.toml` has `sandbox = "workspace-write"` or `"read-only"`
- [ ] `approval_policy` is `"on-request"` or `"untrusted"` — **not** `"never"`
- [ ] Per-project profile override exists for any directory containing production assets or local-only repos

### Gemini CLI
- [ ] `~/.gemini/settings.json` `approvalMode` is **not** `"yolo"`
- [ ] Either: `tools.exclude: ["run_shell_command"]` (recommended) OR `general.sandbox` is set
- [ ] If shell is required, sandbox flavor is explicitly chosen (Docker / Podman / sandbox-exec)

### opencode
- [ ] `opencode.json` contains a `permission` block
- [ ] `permission.bash` is `"ask"` or `"deny"` — not absent (default is permissive)
- [ ] `permission.edit` and `permission.webfetch` are gated for production projects

### Project-level (regardless of agent)
- [ ] `.superharness/profile.yaml` declares trust level for the project
- [ ] Watcher mode chosen: `--print-only` for queue visibility without execution, full bypass flags only for trusted contracts
- [ ] `~/.git-push-allowlist` includes (or excludes) this project intentionally
- [ ] `~/.githooks/pre-commit` is the active hook path (verifies filesystem-level gates are in force)

---

## Threat model summary

Superharness is a **task router and lifecycle manager**, not a sandbox. The security guarantees it provides are:

✅ Plan-approval gate for normal (non-`round-*`) tasks
✅ Stale-state cleanup (failed tasks don't block the queue indefinitely)
✅ Deadline enforcement (runaway tasks get auto-failed)
✅ Operator confirmation flags for unattended CLI bypass modes (see `SECURITY.md`)
✅ Per-agent adapter isolation (each agent uses its native policy mechanism)

❌ Superharness does **not** verify that target agents have safe policies before dispatching
❌ Superharness does **not** override an agent's native gates — your allowlist is the gate
❌ Superharness does **not** apply uniform policy across agents — drift between agents is possible
❌ Superharness does **not** enforce filesystem-level isolation — that's the agent's sandbox or the OS

For projects where the threat model requires more than this, additional layers are needed:
- **OS-level sandboxing**: Docker, Podman, sandbox-exec, or a dedicated VM per project
- **Filesystem-level hooks**: pre-commit / pre-push guards that catch destructive operations downstream
- **Network-level isolation**: deny outbound traffic from the agent's process group

Existing examples in the wider workspace:
- NemoClaw sandbox for OpenClaw agent — full process isolation + MCP-only tool surface
- `~/.githooks/pre-commit` — filesystem-level enforcement that applies to every agent
- `~/.git-push-allowlist` — push gating regardless of which agent staged the commit

---

## See also

- `SECURITY.md` — dangerous CLI bypass flags and required confirmations
- `src/superharness/engine/lifecycle_rules.py` — full lifecycle rule table
- `src/superharness/commands/auto_dispatch.py` — auto-dispatch and the `round-*` bypass
- `protocol/spec.md` — task lifecycle definitions
- External: `disler/bash-damage-from-within` — L1–L5 framework that informed this analysis
