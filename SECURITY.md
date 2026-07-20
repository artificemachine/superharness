# Security Notes

## Dangerous unattended modes

`superharness` can launch Claude Code and Codex CLI in unattended mode. Two flags are materially more dangerous than normal automation:

- `claude -p --dangerously-skip-permissions`
- `codex exec --dangerously-bypass-approvals-and-sandbox`

These modes disable the normal permission and sandbox checks of the target CLI. Use them only when you trust the project, contract, handoff, and inbox content.

## Required confirmations

**Exactly one variable gates unattended dispatch:**

- `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES`

`shux delegate` refuses to launch non-interactively without it when stdin is not
a TTY (`src/superharness/commands/delegate.py`, `_confirm_non_interactive_risk`).

Two further variables exist:

- `SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES`
- `SUPERHARNESS_CONFIRM_CODEX_BYPASS=YES`

**These are consumed only by the service installers**
(`install-launchd-inbox-watcher.sh`, `install-systemd-inbox-watcher.sh`), which
prompt for them and bake the result into the generated plist/unit file. They are
**not** re-checked at dispatch time. Once a dispatch is non-interactive,
`delegate-to-claude.sh` appends `-p --dangerously-skip-permissions` and
`delegate-to-codex.sh` appends `--dangerously-bypass-approvals-and-sandbox`
based on the `--non-interactive` / `--codex-bypass` flags alone.

Additionally, a project profile with `autonomy: autonomous` causes
`delegate.py` to set both `SUPERHARNESS_CONFIRM_NON_INTERACTIVE` and
`SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS` to `YES` on your behalf.

**What this means in practice:** treat `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES`
— or `autonomy: autonomous` in `profile.yaml` — as sufficient on its own to allow
Claude to run with permission checks disabled. There is no independent second
gate protecting the bypass flags at dispatch time. Grant unattended mode only for
projects whose contract, handoff, and inbox content you trust.

> Prior versions of this document claimed each bypass had its own confirmation
> gate. That was inaccurate and is corrected here; see
> `docs/audits/2026-07-20-job-ready-v2.md`.

## launchd watcher guidance

For macOS watcher installs:

- prefer `--print-only` if you want queue visibility without unattended execution
- only pass `--confirm-skip-permissions yes` when the watcher is allowed to launch Claude without permission prompts
- only pass `--codex-bypass --confirm-codex-bypass yes` when the watcher is allowed to launch Codex outside sandbox and approval controls

Recommended default:

```bash
bash src/superharness/scripts/install-launchd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30 \
  --to codex-cli \
  --confirm-non-interactive yes
```

Higher-risk Claude watcher:

```bash
bash src/superharness/scripts/install-launchd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30 \
  --to claude-code \
  --confirm-non-interactive yes \
  --confirm-skip-permissions yes
```

Highest-risk Codex bypass watcher:

```bash
bash src/superharness/scripts/install-launchd-inbox-watcher.sh \
  --project /path/to/project \
  --interval 30 \
  --to codex-cli \
  --codex-bypass \
  --confirm-non-interactive yes \
  --confirm-codex-bypass yes
```
