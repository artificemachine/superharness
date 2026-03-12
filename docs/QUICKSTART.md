# superharness Quickstart

Shortest path from clone to first dispatch.

**Prerequisites:** `bash`, `ruby`, `python3`. Run `superharness doctor` after install to verify.

```bash
pip install -r requirements.txt   # pytest (for running tests)
```

## Adoption tiers

You don't need to set up everything at once. Start with what you need:

| Tier | Setup | What you get |
|------|-------|--------------|
| **Minimal** | install-wrapper + init | Contracts, handoffs, ledger — no agent CLIs required |
| **Interactive** | + `claude` or `codex` CLI | Live delegation with `delegate --to` |
| **Background** | + launchd/systemd | Unattended auto-dispatch while you work on something else |

The steps below cover the full path. Steps 1-3 are all you need for the minimal tier.

---

## 0) Install the CLI wrapper

Creates a symlink at `~/.local/bin/superharness` pointing to the repo wrapper.

```bash
# From the superharness repo root:
bash scripts/install-wrapper.sh

# If ~/.local/bin is not in your PATH, add it:
export PATH="$HOME/.local/bin:$PATH"
```

## 1) Install Claude Code hooks (optional)

Only needed if you use Claude Code as a delegation target:

```bash
bash adapters/claude-code/install.sh
```

## 2) Initialize your project

This creates `.superharness/` (protocol state) plus `CLAUDE.md` and `AGENTS.md` in your project root.

```bash
cd /path/to/your/project
superharness init "My Project" "Node/TypeScript" "active"
```

> `CLAUDE.md` and `AGENTS.md` are agent configuration files — review and customize them for your project. If they already exist, `init` will skip them.

**Decide whether to commit `.superharness/` state files:**

```bash
# Option A — ignore (recommended for personal/solo projects):
echo '.superharness/' >> .gitignore

# Option B — commit (recommended for team projects where all agents share state):
git add .superharness/
```

## 3) Verify setup

```bash
superharness doctor --project .
```

All checks should pass (except the watcher, which you haven't started yet).

## 4) Create a task and enqueue it

```bash
superharness task create --project . --id demo-task --title "Run first delegation" --owner codex-cli
superharness enqueue --project . --to codex-cli --task demo-task --priority 1
```

## 5) Preview the dispatch prompt (safe — does not launch anything)

```bash
superharness dispatch --project . --to codex-cli --print-only
```

## 6) Run the watcher

**Foreground (any platform — Linux, macOS, Docker, CI):**
```bash
superharness watch --foreground --project . --interval 30
```

**In Docker / CI (non-interactive):**
```bash
superharness watch --foreground --project . --interval 60 \
  --non-interactive --launcher-timeout 300
```
Set `SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES` in the environment to confirm unattended execution.

**Background on Linux (systemd):**
```bash
# Copy the template unit file
cp scripts/superharness-watcher@.service ~/.config/systemd/user/

# Enable and start for your project directory (relative to $HOME)
# Example: project at ~/myproject → instance name "myproject"
systemctl --user enable --now superharness-watcher@myproject.service
systemctl --user status superharness-watcher@myproject.service
```

**Background on macOS (launchd):**
```bash
bash scripts/install-launchd-inbox-watcher.sh --project . --interval 30 \
  --confirm-non-interactive yes --confirm-skip-permissions yes
```

## 7) Cleanup and hygiene (optional)

```bash
superharness recover --project . --timeout-minutes 20 --action stale
superharness hygiene --project .
```

## Uninstall

```bash
superharness uninstall --dry-run   # preview what would be removed
superharness uninstall --all       # remove all system artifacts
```

## 8) Run the test suite (optional)

```bash
pip install -r requirements.txt
pytest tests/ -q
```

---

## Notes

- `--print-only` never launches CLI processes — safe for exploration.
- All commands accept `--help` for full usage info.
- Check version: `superharness --version`
- For the full command reference, see [GUIDE.md](GUIDE.md).
