# superharness Command Reference

Full command reference for superharness. For first-time setup, see the [Quick Start](../README.md#quick-start) section in the README.

---

## Install Wrapper into PATH

```bash
bash scripts/install-wrapper.sh
```

Symlinks the wrapper to `~/.local/bin/superharness`. Add `~/.local/bin` to your PATH if not already present. After that, use `superharness <command>` from anywhere.

---

## Init

Bootstrap protocol files in a project directory:

```bash
# Explicit (recommended for humans):
superharness init "My Project" "Python/Docker" "active"

# Auto-detect stack and status from project files (no args needed):
superharness init --detect

# From an agent-written profile.yaml (recommended for AI-driven installs):
superharness init --from-profile .superharness/profile.yaml
```

All three modes create `.superharness/`, `CLAUDE.md`, and `AGENTS.md`. `--detect`
and `--from-profile` skip the positional arguments. See [docs/INSTALL-AGENT.md](INSTALL-AGENT.md)
for the full agent-driven install flow.

---

## Core Commands

### Delegation

Launch a session for the next pending task:

```bash
superharness delegate --to codex-cli --project /path/to/project
superharness delegate --to claude-code --project /path/to/project
```

**Options:**
- `--task <TASK_ID>` — force a specific task (bypasses next-task logic)
- `--print-only` — generate prompt text without launching the CLI
- `--directive "extra instructions"` — append custom directive to prompt

**Shorthand by task id (auto-routes to task owner):**
```bash
superharness delegate mcp-docs --project /path/to/project --print-only
```

### Contract snapshot

```bash
superharness contract today --project /path/to/project
```

Prints all tasks with id, status, owner, and suggests the next task to work on.

### Task management

```bash
# Guided interactive wizard
superharness task

# Create task
superharness task create --project . --id task-id --title "Task title" --owner codex-cli

# Create task with dependency
superharness task create --project . --id test-task --title "Run tests" --owner codex-cli --dependency task-id

# Update task status
superharness task status --project . --id task-id --status in_progress --actor codex-cli

# Delete task
superharness task delete --project . --id task-id
```

### Inbox queue

**Enqueue a task:**
```bash
superharness enqueue --project . --to codex-cli --task task-id --priority 1
```

**Dispatch next pending item:**
```bash
superharness dispatch --project . --to codex-cli
```

Use `--print-only` to preview without launching.

**Start watcher (foreground):**
```bash
superharness watch --project . --to both
```

**Inbox status flow:**
1. `pending` → `launched` (dispatch claims item; retry count increments)
2. `launched` → `running` (agent begins work)
3. `running` → `done` or `failed` (agent completes or errors)
4. `pending` → `paused` (skipped this cycle — dirty worktree or plan gate pending)

### Inbox maintenance

**Recover stale launched items:**
```bash
superharness recover --project . --timeout-minutes 20 --action stale
```

**Normalize inbox (archive done/failed):**
```bash
superharness normalize --project . --archive
```

Archives `done` and `failed` items to `.superharness/inbox-archive.yaml`.

---

## Project Auto-Detection

Most commands require `--project DIR`. To avoid repeating it:

1. **Auto-detect from cwd:** If `.superharness/` exists in the current directory, `--project .` is injected automatically.
2. **Environment variable:** Set `SUPERHARNESS_PROJECT=/path/to/project` to use a fixed project directory.
3. **Explicit flag:** `--project DIR` always takes precedence.

---

## Background Watcher

**macOS (launchd):**
```bash
bash scripts/install-launchd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30 \
  --confirm-non-interactive yes \
  --confirm-skip-permissions yes
```

**Linux (systemd):**
```bash
cp scripts/superharness-watcher@.service ~/.config/systemd/user/
systemctl --user enable --now superharness-watcher@myproject.service
```

**Uninstall watcher:**
```bash
superharness uninstall --project /path/to/project
```

**Notes:**
- Avoid `~/Documents`, `~/Desktop`, `~/Downloads` for watcher-managed projects on macOS — launchd can fail with `Operation not permitted`.
- Watcher logs: `~/Library/Logs/superharness/com.superharness.inbox.<project-name>-.out.log`

**Required env vars for unattended dispatch:**
- `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES`
- `SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES`

---

## Protocol Hygiene

```bash
superharness hygiene --project .
superharness hygiene --project . --strict   # requires promotion alignment
```

**What hygiene checks validate:**
- Contract YAML structure and required fields
- Task status transitions (no invalid states)
- Handoff files match done tasks
- Ledger entries exist for completed work
- Decisions/failures promotion alignment (strict mode only)

**Failure-memory promotion workflow:**
1. Record task-local incidents in `.superharness/contract.yaml` under `failures`.
2. Promote reusable incidents to `.superharness/failures.yaml`.
3. Keep strict hygiene green by ensuring promoted failures are not left only in the contract.

---

## Doctor Checks

```bash
superharness doctor --project .
```

Checks for: required executables (`bash`, `ruby`, `python3`, `claude`, `codex`), protocol directory structure, YAML syntax validity, file permissions.

---

## Monitor UI

```bash
superharness monitor-ui --project .
```

Includes: watcher state, inbox counters, one-click queue actions, plan confirmation buttons, optional Logdy log view.

**Security:** binds to loopback only (127.0.0.1), mutating actions require per-session token printed to terminal on startup.

---

## Readiness Audits

Use this for a generic cross-repo quality audit (in Claude Code):
```
/production-ready
```

Use this for superharness-specific release quality policy:
```
/superharness-production-ready
```

Rule of thumb:
- Use `/production-ready` for any repository.
- Use `/superharness-production-ready` for this repo to run local mandatory checks (contract protocol hygiene, regression guard, watcher/doctor posture).

**Run shell entrypoint guard:**
```bash
bash scripts/check-shell-entrypoints.sh
```

**Install git pre-commit hook:**
```bash
bash scripts/install-git-hooks.sh
```

---

## Troubleshooting

### Watcher not dispatching

```bash
tail -f ~/Library/Logs/superharness/com.superharness.inbox.<project-name>-.out.log
```

**Common causes:**
- `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES` not set in plist
- Project path in restricted directory (`~/Documents`, `~/Desktop`, `~/Downloads`)
- `codex` or `claude` CLI not in PATH
- Stale lock: `rmdir .superharness/inbox.yaml.lock.d/` if no dispatch is running

### Inbox items stuck in `launched`

```bash
superharness recover --project . --timeout-minutes 20 --action stale
```

### Hygiene failures

```bash
superharness hygiene --project .
```

**Common fixes:**
- Missing handoff for done task → create handoff YAML in `.superharness/handoffs/`
- Missing ledger entry → append one line to `.superharness/ledger.md`
- Contract decisions not promoted → move reusable decisions to `.superharness/decisions.yaml`

### Ruby not found

```
/usr/bin/env: ruby: No such file or directory
```

Install Ruby:
- macOS: `brew install ruby` then add to PATH: `export PATH="$(brew --prefix ruby)/bin:$PATH"`
- Linux: `sudo apt install ruby-full` or `sudo dnf install ruby`
- Version manager: `rbenv install $(cat .ruby-version)` from the superharness repo root

### Claude or Codex CLI not found

```
claude: command not found
codex: command not found
```

Install:
- Claude CLI: `npm install -g @anthropic-ai/claude-code`
- Codex CLI: `npm install -g @openai/codex`

These are optional — only required if you use `delegate --to claude-code` or `delegate --to codex-cli`. `dispatch --print-only` works without them.

### launchd watcher not loading (macOS)

Check whether the plist loaded:
```bash
launchctl list | grep superharness
```

If missing, reload manually:
```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.superharness.inbox.<project-name>-.plist
```

**Common causes:**
- Project path is in `~/Documents`, `~/Desktop`, or `~/Downloads` — macOS sandbox blocks launchd there. Move the project or use `superharness watch --foreground` instead.
- Missing `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES` in the plist `EnvironmentVariables` block — re-run install with `--confirm-non-interactive yes`.
- Plist has wrong path after repo move — re-run `scripts/install-launchd-inbox-watcher.sh`.

View launchd error logs:
```bash
log show --predicate 'process == "launchd"' --last 5m | grep superharness
```

---

---

## Teams

### Commit `.superharness/` or ignore it?

| Scenario | Recommendation |
|----------|----------------|
| Solo / personal | `echo '.superharness/' >> .gitignore` |
| Team / shared agents | `git add .superharness/` — everyone reads the same contract |
| Agents opening PRs | Commit — agents read `contract.yaml` before each session |

### Task ownership

Tasks have an `owner` field (`claude-code` or `codex-cli`). Assign by agent type, not person — any team member can launch the owning agent.

### Concurrency

superharness uses file-based locking (`inbox.yaml.lock.d/`) — two watchers on the same directory won't double-dispatch. Avoid running watchers from different machines on the same directory (locking is local).

### CI (Linux, foreground mode)

```bash
SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES \
superharness watch --foreground --project . --interval 60 --launcher-timeout 300
```

### Onboarding a new team member

```bash
# Pull (if .superharness/ is committed)
git pull
bash /path/to/superharness/scripts/install-wrapper.sh
superharness doctor --project .
superharness contract today --project .   # pick up where the last session left off
```

---

## See Also

- **Architecture:** [ARCHITECTURE.md](ARCHITECTURE.md) — how superharness works internally
- **Security:** [SECURITY.md](../SECURITY.md) — threat model and mitigations
- **Changelog:** [CHANGELOG.md](../CHANGELOG.md) — version history
