# Portable Paths Cleanup — Cross-Repo TDD Plan

**Status:** proposed (2026-05-08)
**Scope:** superharness, obsidian-semantic-mcp, voice-toolkit, agent configs

## Context

Agent configs (`~/.claude/settings.json`, `~/.claude.json`, `~/.opencode.json`,
`~/.pi/agent/mcp.json`, `~/.gemini/projects.json`) hardcode absolute paths to
this repo's hook scripts, MCP server scripts, and project directories. These
paths break under three scenarios:

1. **Repo moves** — rename the workspace directory, restructure tree, move to a different
   home directory.
2. **Release installs** — `pip install superharness`, `uv tool install
   obsidian-semantic-mcp`, Homebrew, etc. The release artifact does not live
   under the workspace directory.
3. **Worktrees** — temp worktree paths (e.g.
   `/private/var/folders/.../superharness-worktrees/<branch>/...`) get baked
   into settings.json by tooling and silently break after worktree cleanup.

This session hit #3 directly: a stale worktree path in `~/.claude/settings.json`
caused 5 broken hook references, which I "fixed" by repointing to the live
source tree — but that's still hardcoded and breaks for a release user.

## Principle

**Tools own their asset paths.** Agent configs reference tools by bare CLI
name on PATH. Each tool exposes its own assets via its own CLI. This
matches how `git-lfs install`, `gh extension install`, `pre-commit install`,
and similar tools work.

## TDD plan — three phases

Each phase is independent. Each cycle is RED → GREEN → REFACTOR. The plan
finishes with phase 4: agent-config migration, which depends on phases 1-3.

---

### Phase 1 — superharness: `superharness adapter-path` CLI

**RED**

Add test `tests/cli/test_adapter_path.py`:

```python
def test_adapter_path_resolves_for_editable_install(tmp_path):
    result = subprocess.run(
        ["superharness", "adapter-path", "claude-code", "session-stop"],
        capture_output=True, text=True, check=True,
    )
    path = Path(result.stdout.strip())
    assert path.is_file(), f"adapter-path returned non-existent {path}"
    assert path.read_text().startswith("#!/bin/bash"), "not the hook script"

def test_adapter_path_resolves_after_repo_move(monkeypatch, tmp_path):
    # Simulate: install to a non-source location, source dir is gone
    fake_install = tmp_path / "site-packages" / "superharness"
    shutil.copytree(SUPERHARNESS_SRC, fake_install)
    monkeypatch.syspath_prepend(str(tmp_path / "site-packages"))
    # Run resolution
    from superharness.cli import adapter_path
    p = adapter_path("claude-code", "session-stop")
    assert p.exists()
    assert str(fake_install) in str(p)

def test_adapter_path_unknown_host_or_hook_errors():
    result = subprocess.run(
        ["superharness", "adapter-path", "bogus", "session-stop"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "unknown host" in result.stderr.lower()
```

**GREEN**

Add `src/superharness/cli/adapter_path.py`:

```python
from importlib.resources import files

KNOWN_HOSTS = {"claude-code", "codex-cli", "pi", "gemini", "hermes"}
KNOWN_HOOKS_BY_HOST = {
    "claude-code": {"session-start", "session-stop", "scope-guard",
                    "branch-guard", "ledger-append"},
    # ... others
}

def adapter_path(host: str, hook: str) -> Path:
    if host not in KNOWN_HOSTS:
        raise ValueError(f"unknown host: {host}")
    if hook not in KNOWN_HOOKS_BY_HOST.get(host, set()):
        raise ValueError(f"unknown hook for {host}: {hook}")
    p = files("superharness") / f"adapters/{host}/hooks/{hook}.sh"
    if not p.is_file():
        raise FileNotFoundError(p)
    return Path(str(p))
```

Wire up as a Typer/Click subcommand on the existing `superharness` CLI.

**REFACTOR**

Move host/hook constants to a single source-of-truth (e.g.
`adapter_manifests/*.yaml` already exists per `pyproject.toml` package data).
Driver consumes the manifests so adding a new host/hook is data-only.

---

### Phase 2 — obsidian-semantic-mcp: bare CLI invocation

**RED**

Add test `tests/test_launcher_cli.py`:

```python
def test_bare_cli_responds_to_initialize(tmp_path):
    """Calling `obsidian-semantic-mcp` with no args (env-driven config) must
    respond to an MCP `initialize` request within 30 seconds."""
    env = os.environ.copy()
    env["OBSIDIAN_VAULT"] = str(tmp_path / "vault")
    env["DATABASE_URL"] = "postgresql://test:test@localhost/test_brain"
    (tmp_path / "vault").mkdir()
    p = subprocess.Popen(
        ["obsidian-semantic-mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=env, bufsize=0,
    )
    p.stdin.write(_initialize_request().encode() + b"\n")
    p.stdin.flush()
    line = _read_with_timeout(p.stdout, 30.0)
    assert b'"result"' in line
    p.terminate()

def test_repo_move_preserves_cli_resolution(tmp_path):
    # Move repo, set OSM_PROJECT_ROOT to new location, verify `which obsidian-semantic-mcp` still resolves
    ...
```

**GREEN**

Verify the existing `launcher.py` already does the right thing for bare-CLI
mode. If it doesn't, fix the resolution order in `_project_root()` so the
launcher can find Docker / vault / DB without `--project-directory`.

Update `~/.claude.json` template in CLAUDE.md to drop `--project-directory`
and rely on `OSM_PROJECT_ROOT` env or the config file at
`~/.config/obsidian-semantic-mcp/project_root`.

**REFACTOR**

Remove the deprecated `scripts/obsidian-semantic-mcp` shim (already marked
deprecated in its source comments) once the migration is complete and no
agent config references it.

**Separate concern (do NOT bundle):** the May 8 transport hang in
`server.py`'s stdin reader. Tracked in `docs/PLAN-portable-mcp-config.md`
under "Known separate bug." Fix in its own RED → GREEN → REFACTOR cycle:
test that `for line in sys.stdin.buffer` doesn't block indefinitely on
anonymous pipes, fix with `anyio.to_thread.run_sync(readline)`, refactor
to consider switching back to the SDK's `stdio_server()` if the upstream
EOF death is now fixed.

---

### Phase 3 — voice-toolkit: documentation + opencode config update

**RED**

Add test `tests/test_console_script_on_path.py`:

```python
def test_voice_toolkit_console_script_is_resolvable():
    p = subprocess.run(["which", "voice-toolkit"], capture_output=True, text=True)
    assert p.returncode == 0
    assert "voice-toolkit" in p.stdout
    # Smoke: can spawn and exit cleanly
    proc = subprocess.Popen(["voice-toolkit"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.stdin.write(_initialize_request().encode() + b"\n")
    proc.stdin.flush()
    proc.stdin.close()
    out = proc.stdout.read(timeout=10)
    assert b'"result"' in out
```

**GREEN**

Mostly already passes; the `voice-toolkit` console script is declared in
`pyproject.toml`. The deliverable here is a CLAUDE.md update with corrected
agent-config templates (bare `voice-toolkit` everywhere except Claude
Desktop).

**REFACTOR**

Audit `voice-toolkit-register` (the multi-client install helper) to use
bare CLI names by default for all hosts, with the Claude-Desktop carve-out
documented in one place.

---

### Phase 4 — agent-config migration (depends on 1-3)

**RED**

Add an integration test (likely in superharness, since it owns the agent-
infra concept) that:

1. Snapshots the user's agent configs (settings.json, claude.json, etc.)
2. Simulates a repo move by `mv`-ing a project dir to a tmp location.
3. Runs each MCP server / hook command from the snapshot.
4. Asserts none break.

The test fails today (paths are absolute and break on move). Fixing it
requires migrating each config entry to bare CLI names.

**GREEN**

Mechanical migration:

| File | Change |
|---|---|
| `~/.claude/settings.json` (Stop, SessionStart, PreToolUse, PostToolUse hooks) | Replace 5 hardcoded bash paths with `bash $(superharness adapter-path claude-code <hook>)` |
| `~/.claude.json` (obsidian-semantic, voice-toolkit MCP entries) | Replace `docker compose exec ...` and absolute scripts with bare `obsidian-semantic-mcp` and `voice-toolkit` |
| `~/.opencode.json` | Same as claude.json migration |
| `~/.pi/agent/mcp.json` | Same |
| `~/.gemini/projects.json`, `trustedFolders.json` | Lower priority — these are project registries, not runtime hooks. Leave for the user to clean up manually after a move. |

**REFACTOR**

After migration, the `~/.claude/hooks/superharness-stop-no-mcp-kill.sh`
wrapper I shipped this session can either:
1. Be replaced by an upstream fix in superharness (drop the pkill block
   from session-stop.sh), or
2. Use `superharness adapter-path` directly:
   ```bash
   REAL="$(superharness adapter-path claude-code session-stop)"
   bash <(grep -v '^pkill -TERM -f' "$REAL")
   ```
   Eliminating the dev-tree fallback hack entirely.

The right answer is (1) upstream fix; (2) is a stable interim wrapper.

---

## Out of scope for this plan

- `~/.gemini/`, `~/.hermes/` session log files containing hardcoded paths
  in past tool-call arguments — these are historical and don't affect
  runtime behavior.
- `~/.claude/commands/*.md` references to `/Users/airm2max/Documents/
  DevOpsCelstn/` — these are documented examples in user-authored slash
  commands; the user can update them as part of their own command
  maintenance.
- `~/.codex/` — explicitly off-limits per global rules.

## Verification of the whole

After all four phases:

```bash
# Move every project to a new location.
mkdir -p ~/sandbox && \
  mv ~/superharness ~/sandbox/ && \
  mv ~/obsidian-semantic-mcp ~/sandbox/ && \
  mv ~/voice-toolkit ~/sandbox/

# Reinstall each via pip / uv (release-style).
pip install -e ~/sandbox/superharness
pip install -e ~/sandbox/obsidian-semantic-mcp
pip install -e ~/sandbox/voice-toolkit

# Restart Claude Code. /mcp should show all servers connected.
# Trigger Stop hook (end any turn). superharness session-progress.md should
# update for the active project.

# Move back. Repeat. Should still work without re-editing any config file.
```

If the full move-and-back cycle works without any manual edits to
`~/.claude/settings.json` or `~/.claude.json`, the cleanup is done.

## Order of operations

1. Phase 1 (superharness CLI) — must ship first; phase 4 depends on it.
2. Phase 2 (obsidian-semantic CLI) — independent of 1.
3. Phase 3 (voice-toolkit docs) — independent of 1, 2.
4. Phase 4 (agent-config migration) — depends on 1, 2, 3.

Phases 1, 2, 3 can run in parallel (different repos).
