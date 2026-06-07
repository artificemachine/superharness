"""doctor command — check local setup and project protocol health."""
from __future__ import annotations

import os
import pathlib
import platform
import shutil
import subprocess
import sys

import logging
logger = logging.getLogger(__name__)

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent


def _install_hint(dep: str) -> str:
    is_mac = platform.system() == "Darwin"
    hints = {
        "python3": "brew install python3" if is_mac else "sudo apt install python3   # or: sudo dnf install python3",
        "claude": "npm i -g @anthropic-ai/claude-code",
        "codex": "npm i -g @openai/codex",
    }
    return hints.get(dep, "")


def get_doctor_summary(project_dir: str) -> str:
    """Run doctor checks internally and return a compact summary string."""
    import io
    from contextlib import redirect_stdout
    
    f = io.StringIO()
    try:
        with redirect_stdout(f):
            # Run the main logic with no args
            main(["--project", project_dir])
    except SystemExit:
        pass
    except Exception as e:
        return f"Error running doctor: {e}"
        
    raw = f.getvalue()
    # Filter for FAIL/WARN lines and the summary
    lines = []
    for line in raw.splitlines():
        if "FAIL" in line or "WARN" in line or "summary:" in line:
            lines.append(line.strip())
            
    # Add git status check (crucial for autonomous retries)
    try:
        r = subprocess.run(
            ["git", "-C", project_dir, "status", "--porcelain"],
            capture_output=True, text=True, check=False, timeout=2
        )
        if r.stdout.strip():
            count = len(r.stdout.strip().splitlines())
            lines.insert(0, f"WARN git:working tree is dirty ({count} modified files)")
    except Exception as e:
        logger.warning("doctor.py unexpected error: %s", e, exc_info=True)
        pass
    if not lines:
        return "System health: ok"
        
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(
        prog="doctor",
        description="Check local setup and project health (prerequisites, watcher, protocol files).",
    )
    p.add_argument("-p", "--project", default=os.getcwd(),
                   help="Project directory to check (default: current directory)")
    p.add_argument("--check", action="store_true",
                   help="Exit with non-zero status if any check fails (useful in CI)")
    opts = p.parse_args(argv)

    project_dir = os.path.realpath(opts.project)
    if not os.path.isdir(project_dir):
        sys.exit(f"Project directory does not exist: {opts.project}")

    failures = 0
    warns = 0

    def check_dep(dep: str) -> None:
        nonlocal warns
        if shutil.which(dep):
            print(f"PASS dep:{dep}")
        else:
            print(f"WARN dep:{dep} missing")
            hint = _install_hint(dep)
            if hint:
                print(f"       {hint}")
            warns += 1

    print("superharness doctor")
    print(f"project: {project_dir}")

    check_dep("python3")
    check_dep("claude")
    check_dep("codex")

    harness_dir = os.path.join(project_dir, ".superharness")
    if os.path.isdir(harness_dir):
        print("PASS project:.superharness present")
    else:
        print("FAIL project:.superharness missing")
        print('       Run: superharness init "Project" "Stack" "active"')
        failures += 1

    home = os.path.expanduser("~")
    protected = [os.path.join(home, d) for d in ("Documents", "Desktop", "Downloads")]
    if any(project_dir.startswith(p + os.sep) or project_dir == p for p in protected):  # shipguard:ignore PY-004
        print("WARN project:path is macOS protected folder (launchd may fail: Operation not permitted)")
        warns += 1

    for fname in ("ledger.md",):
        fpath = os.path.join(harness_dir, fname)
        if os.path.isfile(fpath):
            print(f"PASS file:{fname}")
        else:
            print(f"FAIL file:{fname} missing")
            print("       Re-initialize: superharness init")
            failures += 1

    # State lives in SQLite — contract.yaml, decisions.yaml, failures.yaml are export-only.
    # The state-db check below confirms SQLite is healthy instead.

    if os.path.isdir(os.path.join(harness_dir, "handoffs")):
        print("PASS dir:handoffs")
    else:
        print("FAIL dir:handoffs missing")
        print("       Run: mkdir -p .superharness/handoffs")
        failures += 1

    # git hooks check
    try:
        r = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            r2 = subprocess.run(
                ["git", "-C", project_dir, "config", "--get", "core.hooksPath"],
                capture_output=True, text=True
            )
            hooks_path = r2.stdout.strip()
            if hooks_path == ".githooks":
                print("PASS git:core.hooksPath=.githooks")
            elif hooks_path:
                # Accept any path that resolves to an existing directory (e.g. ~/.githooks)
                resolved = pathlib.Path(hooks_path).expanduser()
                if not resolved.is_absolute():
                    resolved = pathlib.Path(project_dir) / resolved
                if resolved.is_dir():
                    print(f"PASS git:core.hooksPath={hooks_path}")
                else:
                    print(f"WARN git:core.hooksPath={hooks_path} (directory not found)")
                    warns += 1
            else:
                print("WARN git:core.hooksPath not set")
                print("       Run: git config core.hooksPath .githooks")
                warns += 1
        else:
            print("WARN git:not a git repository")
            warns += 1
    except FileNotFoundError:
        print("WARN git:not found")
        warns += 1

    # Claude Code plugin check
    plugin_path = pathlib.Path.home() / ".claude" / "plugins" / "superharness"
    if plugin_path.exists():
        print("PASS plugin:claude-code superharness installed")
    else:
        print("WARN plugin:claude-code superharness not installed")
        adapter_install = _REPO_ROOT / "adapters" / "claude-code" / "install.sh"
        if adapter_install.exists():
            print(f"       Run: bash {adapter_install}")
        else:
            print("       Run: bash adapters/claude-code/install.sh  (from superharness repo)")
        warns += 1

    # watcher check
    sys_platform = platform.system()
    if sys_platform == "Darwin":
        import re
        slug = re.sub(r"[^A-Za-z0-9]+", "-", os.path.basename(project_dir))
        label = f"com.superharness.inbox.{slug}"
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
        if label in r.stdout:
            print(f"PASS watcher:{label} loaded")
        else:
            print(f"WARN watcher:{label} not loaded")
            print("       The background watcher is required — install it with: shux watcher-worker -p .")
            print("       Or use foreground mode instead: superharness watch --foreground --project .")
            warns += 1
    elif sys_platform == "Linux":
        print("INFO watcher:launchd not available (non-macOS)")
        print("       Use foreground mode: superharness watch --foreground --project .")
    else:
        print(f"INFO watcher:platform {sys_platform} — use foreground mode: superharness watch --foreground --project .")

    # Optional: MCP memory server check (informational only)
    mcp_config = pathlib.Path.home() / ".claude" / "settings.json"
    if mcp_config.exists():
        import json as _json
        try:
            settings = _json.loads(mcp_config.read_text(encoding="utf-8"))
            mcp_servers = settings.get("mcpServers", {})
            has_memory = any(
                "mem" in name.lower() or "memory" in name.lower()
                for name in mcp_servers
            )
            if has_memory:
                print("INFO mcp:memory server configured (optional enhancement)")
            else:
                print("INFO mcp:no memory server detected (optional — see docs/MCP-MEMORY.md)")
        except Exception as e:
            logger.warning("doctor.py unexpected error: %s", e, exc_info=True)
            pass
    # Module health check
    try:
        from superharness.modules.registry import enabled_modules
        import yaml as _yaml
        modules_dir = pathlib.Path(project_dir) / ".superharness" / "modules"
        enabled = enabled_modules(pathlib.Path(project_dir))
        if enabled:
            # Check each enabled module for missing env dependencies
            for mod_name in sorted(enabled):
                mod_file = modules_dir / f"{mod_name}.yaml"
                if mod_file.exists():
                    try:
                        mod_data = _yaml.safe_load(mod_file.read_text(encoding="utf-8"))
                        detect = mod_data.get("detect", {}) if isinstance(mod_data, dict) else {}
                        env_var = detect.get("env") if isinstance(detect, dict) else None
                        if env_var and not os.environ.get(env_var):
                            print(f"WARN module:{mod_name} — {env_var} not set")
                            warns += 1
                    except Exception as e:
                        logger.warning("doctor.py unexpected error: %s", e, exc_info=True)
                        pass
            print(f"PASS modules: {len(enabled)} enabled ({', '.join(sorted(enabled))})")
        else:
            print("INFO modules: none enabled — run 'shux enhance' to add integrations")
    except Exception as e:
        logger.warning("doctor.py unexpected error: %s", e, exc_info=True)
        pass
    # SQLite state DB health. Parity (YAML↔SQLite drift) is trivially
    # PASS post-migration — SQLite is the sole source of truth — but we
    # still emit a parity: line so consumers and tests that grep for it
    # see the current contract.
    from superharness.utils.paths import is_project_initialized, resolve_xdg_state_db_path
    legacy_db = os.path.join(project_dir, ".superharness", "state.sqlite3")
    xdg_db = resolve_xdg_state_db_path(project_dir)
    # Split-brain detection: both XDG and legacy DBs exist simultaneously.
    if os.path.isfile(xdg_db) and os.path.isfile(legacy_db):
        print("WARN state-db: split-brain — both XDG state.db and legacy .superharness/state.sqlite3 exist")
        print(f"  XDG:    {xdg_db}")
        print(f"  Legacy: {legacy_db}")
        print(f"  Run: shux migrate-state --project {project_dir}")
        warns += 1
    if is_project_initialized(project_dir):
        try:
            from superharness.engine.db import get_connection, init_db
            _conn = get_connection(project_dir)
            try:
                init_db(_conn)
                print(f"PASS state-db: state.sqlite3 present and initialised")
                print("PASS parity: SQLite is the sole source of truth (no YAML to drift from)")
            finally:
                _conn.close()
        except Exception as _exc:
            print(f"WARN state-db: check failed ({_exc})")
            print("WARN parity: state-db check failed; cannot verify")
            warns += 1
    else:
        # Check if the project has a legacy state.sqlite3 that hasn't been migrated
        if os.path.isfile(legacy_db):
            print("WARN state-db: legacy .superharness/state.sqlite3 found — project not yet migrated to XDG path")
            print(f"  Run: shux migrate-state --project {project_dir}")
            warns += 1
        else:
            print("INFO state-db: state.sqlite3 not found — run 'shux init' to initialise")
        print("INFO parity: skipped (no state.sqlite3)")

    # Fleet check: user-specific local GPU inference endpoints
    from superharness.engine.model_router import _load_fleet_config
    fleet = _load_fleet_config()
    if fleet:
        endpoints = fleet.get("endpoints", {})
        models = fleet.get("models", {})
        tiers = [t for t in ("max", "standard", "mini", "tiny") if t in models]
        print(f"PASS fleet: {len(tiers)} GPU tier(s) configured ({', '.join(tiers)})")
        for t in tiers:
            ep = endpoints.get(t, "?")
            model = models.get(t, "?")
            print(f"  fleet/{t}: {model} @ {ep}")
        print(f"  Agent: opencode tiers mapped to fleet models")
    else:
        print("INFO fleet: no fleet.yaml found — local GPU inference not configured")
        print("  → Create ~/.config/superharness/fleet.yaml to enable local model routing")

    print(f"summary: failures={failures} warnings={warns}")
    if failures > 0:
        print()
        print("→ Fix the failures above, then re-run 'shux doctor'.")
        sys.exit(1)
    if opts.check and warns > 0:
        sys.exit(1)
    print()
    print("→ Next: run 'shux contract' to see your tasks, or 'shux dashboard' to open the dashboard.")


if __name__ == "__main__":
    main()
