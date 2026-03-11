# Security Notes

## Dangerous unattended modes

`superharness` can launch Claude Code and Codex CLI in unattended mode. Two flags are materially more dangerous than normal automation:

- `claude -p --dangerously-skip-permissions`
- `codex exec --dangerously-bypass-approvals-and-sandbox`

These modes disable the normal permission and sandbox checks of the target CLI. Use them only when you trust the project, contract, handoff, and inbox content.

## Required confirmations

`cli/delegate.sh` and the launchd watcher require explicit confirmation for unattended execution:

- `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES`
- `SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES`
- `SUPERHARNESS_CONFIRM_CODEX_BYPASS=YES`

The generic non-interactive confirmation is not enough to enable the dangerous Claude or Codex bypass flags. Each bypass has its own confirmation gate.

## launchd watcher guidance

For macOS watcher installs:

- prefer `--print-only` if you want queue visibility without unattended execution
- only pass `--confirm-skip-permissions yes` when the watcher is allowed to launch Claude without permission prompts
- only pass `--codex-bypass --confirm-codex-bypass yes` when the watcher is allowed to launch Codex outside sandbox and approval controls

Recommended default:

```bash
bash scripts/install-launchd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30 \
  --to codex-cli \
  --confirm-non-interactive yes
```

Higher-risk Claude watcher:

```bash
bash scripts/install-launchd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30 \
  --to claude-code \
  --confirm-non-interactive yes \
  --confirm-skip-permissions yes
```

Highest-risk Codex bypass watcher:

```bash
bash scripts/install-launchd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30 \
  --to codex-cli \
  --codex-bypass \
  --confirm-non-interactive yes \
  --confirm-codex-bypass yes
```
