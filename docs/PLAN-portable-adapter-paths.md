# Portable Adapter Paths — superharness

## The problem

Agent configs (`~/.claude/settings.json`, `~/.claude.json`, `~/.opencode.json`,
`~/.pi/agent/mcp.json`, etc.) hardcode absolute paths to this repo's adapter
hook scripts:

```
~/.claude/settings.json:209  bash src/superharness/adapters/claude-code/hooks/session-stop.sh
~/.claude/settings.json:245  bash src/superharness/adapters/claude-code/hooks/session-start.sh
~/.claude/settings.json:277  bash src/superharness/adapters/claude-code/hooks/scope-guard.sh
~/.claude/settings.json:287  bash src/superharness/adapters/claude-code/hooks/branch-guard.sh
~/.claude/settings.json:308  bash src/superharness/adapters/claude-code/hooks/ledger-append.sh
```

This breaks for:
- Anyone who moves the repo (rename the workspace directory, restructure tree, etc.)
- Anyone who installs via a release artifact (`pip install superharness`,
  Homebrew, uv tool install) — they have no source checkout to point at.
- Worktrees: a temp worktree path (e.g.
  `/private/var/folders/.../superharness-worktrees/<branch>/...`) gets baked
  into settings.json and persists after the worktree is cleaned up,
  silently breaking hooks until manually fixed.

## What this project must provide

A path-resolution CLI that returns the canonical asset path regardless of
install mode (editable / wheel / brew / uv).

### Proposed CLI

```bash
superharness adapter-path <host> <hook>
# host: claude-code | codex-cli | pi | gemini | hermes
# hook: session-start | session-stop | scope-guard | branch-guard | ledger-append
```

Examples:
```
$ superharness adapter-path claude-code session-stop
src/superharness/adapters/claude-code/hooks/session-stop.sh

$ pip install --upgrade superharness && superharness adapter-path claude-code session-stop
$HOME/.local/pipx/venvs/superharness/lib/python3.13/site-packages/superharness/adapters/claude-code/hooks/session-stop.sh
```

Implementation: `from importlib.resources import files; print(files("superharness") / f"adapters/{host}/hooks/{hook}.sh")`.

Same path resolution works for editable installs, wheel installs, system
installs.

## Acceptance test

```bash
# Move the repo, reinstall via different methods, verify resolution still works.
mv ~/superharness ~/elsewhere/superharness
cd ~/elsewhere/superharness && pip install -e .
superharness adapter-path claude-code session-stop
# Must print the new path. NOT the old path. NOT empty.
```

## Cross-cutting plan

See `docs/PLAN-portable-paths-cleanup.md` (canonical TDD plan) — this project
is phase 1 of the cleanup.

## Memory aid for future Claude sessions

Before editing `~/.claude/settings.json` or any agent config to reference this
repo's hooks: don't hardcode the path. Use `bash "$(superharness adapter-path
claude-code <hook>)"` instead. If the CLI subcommand doesn't exist yet, that's
phase 1 to ship before the agent-config migration.
