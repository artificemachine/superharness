# Unattended Execution

superharness can run agents overnight without human supervision. The background watcher polls the inbox queue, dispatches tasks, and handles failures — all while you sleep.

## How It Works

```
inbox.yaml → watcher polls → dispatch → agent runs → status updated → ledger appended
                ↑                                              |
                └──────────── recover stale items ─────────────┘
```

The watcher is a timer-based service (launchd on macOS, systemd on Linux) that:
1. Reads `inbox.yaml` for pending items
2. Dispatches each item to the target agent (claude-code or codex-cli)
3. Marks items as `launched` → `running` → `done` or `failed`
4. Recovers items stuck in `launched` state after a configurable timeout

## Setup

### macOS (launchd)

```bash
bash scripts/install-launchd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30 \
  --confirm-non-interactive yes \
  --confirm-skip-permissions yes
```

This creates a plist at `~/Library/LaunchAgents/com.superharness.inbox.<project>.plist`.

**Verify:**
```bash
launchctl list | grep superharness
```

**Logs:**
```bash
tail -f ~/Library/Logs/superharness/com.superharness.inbox.<project>.out.log
```

**Stop:**
```bash
launchctl unload ~/Library/LaunchAgents/com.superharness.inbox.<project>.plist
```

### Linux (systemd)

```bash
CONFIRM_NON_INTERACTIVE=yes bash scripts/install-systemd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30
```

This creates two units in `~/.config/systemd/user/`:
- `superharness-inbox-<project>.service` — the oneshot watcher
- `superharness-inbox-<project>.timer` — triggers the service on interval

**Verify:**
```bash
systemctl --user status superharness-inbox-<project>.timer
```

**Logs:**
```bash
journalctl --user -u superharness-inbox-<project>.service
# or:
tail -f ~/.local/share/superharness/logs/superharness-inbox-<project>.out.log
```

**Stop:**
```bash
systemctl --user stop superharness-inbox-<project>.timer
systemctl --user disable superharness-inbox-<project>.timer
```

## What the Ledger Looks Like the Next Morning

After an overnight run with three tasks queued:

```markdown
# Ledger — my-project

- 2026-03-14T22:15:00Z — watcher — DISPATCH: feat-auth to claude-code
- 2026-03-14T22:15:30Z — claude-code — modified: src/auth.py
- 2026-03-14T22:18:45Z — claude-code — VERIFY PASS: feat-auth — pytest all green
- 2026-03-14T22:18:46Z — claude-code — CLOSE: feat-auth — Auth middleware implemented
- 2026-03-14T22:30:00Z — watcher — DISPATCH: fix-typos to claude-code
- 2026-03-14T22:30:15Z — claude-code — modified: README.md, docs/GUIDE.md
- 2026-03-14T22:31:00Z — claude-code — CLOSE: fix-typos — Fixed 4 typos
- 2026-03-14T23:00:00Z — watcher — DISPATCH: refactor-db to codex-cli
- 2026-03-14T23:00:10Z — codex-cli — modified: src/db.py, tests/test_db.py
- 2026-03-14T23:15:00Z — codex-cli — VERIFY PASS: refactor-db — all tests pass
- 2026-03-14T23:15:01Z — codex-cli — CLOSE: refactor-db — DB layer refactored
```

## Failure Handling

When an agent fails:

1. The task status is set to `failed` with a `stopped_reason`
2. A ledger entry records the failure
3. The inbox item is marked `failed`
4. The watcher moves to the next item

**Stale recovery:** If an agent is launched but doesn't report back within `--recover-timeout-minutes` (default: 20), the watcher marks it as stale and optionally retries:

```bash
--recover-action retry   # re-queue the item (default)
--recover-action stale   # mark stale and skip
```

## Configuration Options

| Flag | Default | Description |
|------|---------|-------------|
| `--interval` | 15s | Poll frequency |
| `--to` | both | Target agent filter |
| `--print-only` | off | Preview dispatches without launching |
| `--recover-timeout-minutes` | 20 | Minutes before marking launched items stale |
| `--recover-action` | retry | What to do with stale items |
| `--codex-bypass` | off | Use dangerous bypass for codex (not recommended) |

## Safety

- Every dispatch requires `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES`
- Claude dispatch additionally requires `SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES`
- These are set during install and baked into the service unit
- The watcher never modifies code directly — it only launches agents
- All activity is recorded in the append-only ledger

## Foreground Alternative

If you don't want a system service, use foreground mode:

```bash
superharness watch --foreground --project . --interval 30
```

This runs the same watcher loop in your terminal. Works on macOS, Linux, and Windows. Press Ctrl+C to stop.
