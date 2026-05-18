"""init command — initialize superharness in a project directory."""
from __future__ import annotations

import atexit
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # repo root


def _render_template(src: Path, dst: Path, project_name: str, tech_stack: str,
                     status: str, project_dir: str, date_s: str, identity_block: str = "") -> None:
    text = src.read_text(encoding="utf-8")
    for k, v in {
        "{{PROJECT_NAME}}": project_name,
        "{{TECH_STACK}}": tech_stack,
        "{{STATUS}}": status,
        "{{PROJECT_DIR}}": project_dir,
        "{{DATE}}": date_s,
        "{{IDENTITY_BLOCK}}": identity_block,
    }.items():
        text = text.replace(k, v)
    dst.write_text(text, encoding="utf-8")


def _detect(project_dir: str) -> tuple[str, str, str]:
    """Run detect engine, return (project_name, stack, status)."""
    import yaml
    r = subprocess.run(
        [sys.executable, "-m", "superharness.engine.detect", "--project", project_dir],
        capture_output=True, text=True
    )
    if r.returncode != 0 or not r.stdout.strip():
        return os.path.basename(project_dir), "TBD", "greenfield"
    doc = yaml.safe_load(r.stdout) or {}
    return (
        str(doc.get("project_name") or os.path.basename(project_dir)),
        str(doc.get("stack") or "TBD"),
        str(doc.get("status") or "greenfield"),
    )


def _interactive(project_dir: str) -> tuple[str, str, str, str, bool, str]:
    """Run questionnaire. Returns (project_name, stack, status, goal, install_watcher, tmp_profile)."""
    name, stack, status = _detect(project_dir)
    is_tty = sys.stdin.isatty()

    print("superharness — interactive setup")
    print("================================")
    print()
    print(f"Detected: {stack} project")
    print()

    if is_tty:
        print("? Autonomy level:")
        print("  1. autonomous  — agents act without asking")
        print("  2. supervised  — agents explain, then proceed")
        print("  3. approval-gated — agents wait for explicit approval")
        choice = input("> ").strip() or "2"
    else:
        choice = input("? Autonomy level (1=autonomous 2=supervised 3=approval-gated): ").strip() or "2"

    autonomy = {"1": "autonomous", "3": "approval-gated"}.get(choice, "supervised")

    if is_tty:
        print()
        goal = input("? What are you working on right now? (one sentence)\n> ").strip()
    else:
        goal = input("? Project goal: ").strip()
    goal = goal or "TBD — describe the current objective"

    install_watcher = False
    if platform.system() == "Darwin":
        if is_tty:
            print()
            yn = input("? Enable background watcher? [y/N]\n> ").strip().lower()
        else:
            yn = input("? Enable background watcher? [y/N]: ").strip().lower()
        install_watcher = yn in ("y", "yes")

    # Build a profile doc and write to temp file for reuse
    today = date.today().isoformat()
    import yaml
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, prefix="superharness-profile-")  # shipguard:ignore PY-012
    atexit.register(lambda p=tmp.name: os.path.isfile(p) and os.unlink(p))  # guaranteed cleanup even on exception
    yaml.dump({
        "project_name": name,
        "created": today,
        "autonomy": autonomy,
        "primary_agent": "claude-code",
        "stack": stack,
        "status": status,
    }, tmp, default_flow_style=False, sort_keys=False)
    tmp.close()
    return name, stack, status, goal, install_watcher, tmp.name


def _generate_features(tech_stack: str) -> list[dict]:
    """Generate default features based on detected tech stack."""
    features: list[dict] = [
        {
            "id": "project-builds",
            "category": "core",
            "description": "Project builds without errors",
            "steps": ["Run the build command", "Verify no errors in output"],
            "passes": False,
        },
        {
            "id": "tests-pass",
            "category": "core",
            "description": "All tests pass",
            "steps": ["Run the test suite", "Verify all tests green"],
            "passes": False,
        },
        {
            "id": "cli-entry-point",
            "category": "cli",
            "description": "CLI entry point works",
            "steps": ["Run the CLI with --help or --version", "Verify output"],
            "passes": False,
        },
    ]
    stack_lower = tech_stack.lower()
    if "docker" in stack_lower:
        features.append({
            "id": "docker-build",
            "category": "infra",
            "description": "Docker image builds successfully",
            "steps": ["Run docker build", "Verify image created"],
            "passes": False,
        })
    if "python" in stack_lower:
        features.append({
            "id": "pip-install",
            "category": "integration",
            "description": "Package installs via pip",
            "steps": ["Run pip install -e .", "Verify import works"],
            "passes": False,
        })
    return features


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="init", description="Initialize superharness in a project directory.")
    p.add_argument("project_name", nargs="?", default="",
                   help="Human-readable project name (default: current directory name)")
    p.add_argument("tech_stack", nargs="?", default="",
                   help="Tech stack label, e.g. Python, TypeScript, Go (default: TBD)")
    p.add_argument("status_arg", nargs="?", default="", metavar="STATUS",
                   help="Project status: active, paused, or done (default: active)")
    p.add_argument("-n", "--dry-run", action="store_true",
                   help="Preview what would be created without writing any files")
    p.add_argument("--with-watcher", action="store_true",
                   help="Install background watcher (launchd/systemd) after init")
    p.add_argument("--from-profile", dest="from_profile", default="",
                   help="Bootstrap from a saved profile YAML file")
    p.add_argument("--detect", action="store_true",
                   help="Auto-detect project name and stack from existing files")
    p.add_argument("--interactive", action="store_true",
                   help="Prompt for project name, stack, goal, and watcher install")
    p.add_argument("--refresh", action="store_true",
                   help="Re-run init on an existing project to update templates")
    p.add_argument("--force", action="store_true",
                   help="With --refresh: overwrite CLAUDE.md, AGENTS.md, SOUL.md even if they exist")
    p.add_argument("--skip-hooks", action="store_true",
                   help="Skip auto-installing Claude Code hooks into ~/.claude/settings.json")
    opts = p.parse_args(argv)

    project_dir = str(Path.cwd().resolve())
    today = date.today().isoformat()
    template_dir = _ROOT / "protocol" / "templates"

    interactive_goal = ""
    tmp_profile = ""
    install_watcher = opts.with_watcher or platform.system() == "Darwin"

    if opts.interactive:
        result = _interactive(project_dir)
        project_name, tech_stack, status, interactive_goal, install_watcher_q, tmp_profile = result
        install_watcher = install_watcher_q  # user's explicit choice overrides default
        opts.from_profile = tmp_profile

    if opts.from_profile:
        if not os.path.isfile(opts.from_profile):
            sys.exit(f"Profile file not found: {opts.from_profile}")
        import yaml
        doc = yaml.safe_load(Path(opts.from_profile).read_text(encoding="utf-8")) or {}
        project_name = str(doc.get("project_name") or os.path.basename(project_dir))
        tech_stack = str(doc.get("stack") or "TBD")
        status = str(doc.get("status") or "greenfield")
        print(f"Using profile: {opts.from_profile}")
    elif opts.detect:
        project_name, tech_stack, status = _detect(project_dir)
        print(f"Auto-detected: name={project_name} stack={tech_stack} status={status}")
    else:
        project_name = opts.project_name or os.path.basename(project_dir)
        tech_stack = opts.tech_stack or "TBD"
        status = opts.status_arg or "greenfield"

    print("superharness — init project")
    print("===========================")
    print(f"  Project:  {project_name}")
    print(f"  Stack:    {tech_stack}")
    print(f"  Status:   {status}")
    print(f"  Dir:      {project_dir}")
    print()

    if opts.dry_run:
        print("[dry-run] Would create: .superharness/{handoffs,contracts,review-lenses}")
        print("[dry-run] Would create: .superharness/{failures.yaml,decisions.yaml,ledger.md,contract.yaml}")
        print("[dry-run] Would create if missing: CLAUDE.md, AGENTS.md, GEMINI.md")
        return

    harness = Path(project_dir) / ".superharness"

    if not opts.refresh:
        if harness.is_dir():
            print(".superharness/ already exists. Aborting.")
            print("To re-initialize, remove it first: rm -rf .superharness")
            print("To refresh templates only, use: superharness init --refresh")
            sys.exit(1)

        # Create directories
        (harness / "handoffs").mkdir(parents=True, exist_ok=True)
        (harness / "contracts").mkdir(parents=True, exist_ok=True)
        (harness / "review-lenses").mkdir(parents=True, exist_ok=True)
        (harness / "rules").mkdir(parents=True, exist_ok=True)

        # State lives in SQLite (post-YAML removal). Create the DB at the XDG
        # path so state is never inside the repo and cannot be committed.
        # Bypass get_connection's resolution order by targeting the XDG path
        # directly — .superharness/ was just created above, which would otherwise
        # cause get_connection to fall back to the legacy path.
        try:
            import sqlite3 as _sq
            from superharness.engine.db import init_db
            from superharness.utils.paths import resolve_xdg_state_db_path
            _xdg_db = resolve_xdg_state_db_path(str(project_dir))
            os.makedirs(os.path.dirname(_xdg_db), exist_ok=True)
            _conn = _sq.connect(_xdg_db, timeout=5000)
            _conn.row_factory = _sq.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA foreign_keys=ON")
            try:
                init_db(_conn, str(project_dir))
                _conn.commit()
            finally:
                _conn.close()
        except Exception as _e:
            print(f"warning: failed to initialise state db: {_e}", file=sys.stderr)

        # .gitignore — runtime state only; contract/handoffs/discussions remain tracked
        gitignore_path = harness / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text(
                "# Security — never commit secrets\n"
                ".env\n"
                "*.key\n"
                "*.pem\n"
                "*.p12\n"
                "*.pfx\n"
                "\n"
                "# Runtime state — not version controlled\n"
                "launcher-logs/\n"
                "*.flock\n"
                "*.heartbeat\n"
                "heartbeat.yaml\n"
                "watcher.heartbeat\n"
                "watcher.heartbeat.yaml\n"
                "monitor-health.log\n"
                "session-progress.md\n"
                "session-summary-*.md\n"
                "watcher.yaml\n"
                "modules/\n"
                "contracts/\n"
                "review-lenses/\n"
                "benchmark.jsonl\n"
                "onboarding.yaml\n"
                "daemon.pid.json\n"
                "daemon-state.json\n"
                "operator-state.json\n"
                "trace.jsonl\n"
                "*.lock.d/\n"
                "\n"
                "# SQLite database (WAL files included)\n"
                "state.sqlite3\n"
                "state.sqlite3-shm\n"
                "state.sqlite3-wal\n"
                "\n"
                "# Runtime control files\n"
                "circuit-breaker.json\n"
                ".launchagents_snapshot\n"
                "daemon-monitor.py\n",
                encoding="utf-8"
            )
            print("Created: .superharness/.gitignore (runtime state excluded from git)")

        # ledger.md
        ledger_tmpl = template_dir / "ledger.md"
        if ledger_tmpl.is_file():
            _render_template(ledger_tmpl, harness / "ledger.md", project_name, tech_stack, status, project_dir, today)
        else:
            (harness / "ledger.md").write_text(
                f"# Ledger — {project_name}\n\nAppend-only activity log. Never edit previous entries.\n",
                encoding="utf-8"
            )

        # heartbeat.yaml
        hb_tmpl = template_dir / "heartbeat.yaml"
        if hb_tmpl.is_file():
            shutil.copy2(str(hb_tmpl), str(harness / "heartbeat.yaml"))

        # State lives in SQLite — no contract.yaml created

        # features.json — project feature definition of done
        features_dst = harness / "features.json"
        if not features_dst.exists():
            import json
            features = _generate_features(tech_stack)
            features_dst.write_text(
                json.dumps({"features": features}, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"Created: .superharness/features.json ({len(features)} features)")

    else:  # refresh mode
        if not harness.is_dir():
            sys.exit("--refresh requires an existing .superharness/ directory. Run init first.")
        print("superharness — refresh templates")
        print("================================")
        print(f"  Project:  {project_name}")
        print(f"  Dir:      {project_dir}")
        print()

        # Backfill .gitignore if missing (added in v1.47.8+)
        gitignore_path = harness / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text(
                "# Security — never commit secrets\n"
                ".env\n"
                "*.key\n"
                "*.pem\n"
                "*.p12\n"
                "*.pfx\n"
                "\n"
                "# Runtime state — not version controlled\n"
                "launcher-logs/\n"
                "*.flock\n"
                "*.heartbeat\n"
                "heartbeat.yaml\n"
                "watcher.heartbeat\n"
                "watcher.heartbeat.yaml\n"
                "monitor-health.log\n"
                "session-progress.md\n"
                "session-summary-*.md\n"
                "watcher.yaml\n"
                "modules/\n"
                "contracts/\n"
                "review-lenses/\n"
                "benchmark.jsonl\n"
                "onboarding.yaml\n"
                "daemon.pid.json\n"
                "daemon-state.json\n"
                "operator-state.json\n"
                "trace.jsonl\n"
                "*.lock.d/\n"
                "\n"
                "# SQLite database (WAL files included)\n"
                "state.sqlite3\n"
                "state.sqlite3-shm\n"
                "state.sqlite3-wal\n"
                "\n"
                "# Runtime control files\n"
                "circuit-breaker.json\n"
                ".launchagents_snapshot\n"
                "daemon-monitor.py\n",
                encoding="utf-8"
            )
            print("Created: .superharness/.gitignore (runtime state excluded from git)")

    # Read identity block for template rendering
    identity_src = template_dir / "identity-core.md"
    identity_block = identity_src.read_text(encoding="utf-8") if identity_src.is_file() else ""

    # CLAUDE.md
    claude_dst = Path(project_dir) / "CLAUDE.md"
    _overwrite_user_file = opts.force
    if not claude_dst.exists() or _overwrite_user_file:
        claude_tmpl = template_dir / "CLAUDE.md.template"
        if claude_tmpl.is_file():
            _render_template(claude_tmpl, claude_dst, project_name, tech_stack, status, project_dir, today, identity_block)
        else:
            claude_dst.write_text(
                f"# {project_name}\n\n"
                f"## Identity\n{identity_block}\n\n"
                f"## This Project\n"
                f"- What: {project_name}\n"
                f"- Stack: {tech_stack}\n"
                f"- Status: {status}\n\n"
                f"## Cross-Agent Protocol\n"
                f"- Run `shux contract` before starting work.\n"
                f"- Keep task status, ledger, and handoff updated before stopping.\n",
                encoding="utf-8"
            )
        print("Refreshed: CLAUDE.md" if opts.refresh else "Created: CLAUDE.md")
    else:
        print("Skipped: CLAUDE.md (user-owned — use --force to overwrite)")

    # AGENTS.md
    agents_dst = Path(project_dir) / "AGENTS.md"
    if not agents_dst.exists() or _overwrite_user_file:
        agents_tmpl = template_dir / "AGENTS.md.template"
        if agents_tmpl.is_file():
            _render_template(agents_tmpl, agents_dst, project_name, tech_stack, status, project_dir, today)
        else:
            agents_dst.write_text(
                f"# {project_name}\n\n"
                f"## Identity\nYou are working for the project owner.\n\n"
                f"## This Project\n"
                f"- What: {project_name}\n"
                f"- Stack: {tech_stack}\n"
                f"- Status: {status}\n\n"
                f"## Cross-Agent Protocol\n"
                f"- Run `shux contract` before starting work.\n"
                f"- Keep task status, ledger, and handoff updated before stopping.\n",
                encoding="utf-8"
            )
        print("Refreshed: AGENTS.md" if opts.refresh else "Created: AGENTS.md")
    else:
        print("Skipped: AGENTS.md (user-owned — use --force to overwrite)")

    # GEMINI.md
    gemini_dst = Path(project_dir) / "GEMINI.md"
    if not gemini_dst.exists() or _overwrite_user_file:
        gemini_tmpl = template_dir / "GEMINI.md.template"
        if gemini_tmpl.is_file():
            _render_template(gemini_tmpl, gemini_dst, project_name, tech_stack, status, project_dir, today)
        else:
            gemini_dst.write_text(
                f"# Gemini Agent — {project_name}\n\n"
                f"You are `gemini-cli`, an agent in the superharness multi-agent framework.\n"
                f"Read `.superharness/contract.yaml` to find your task (owner: gemini-cli).\n"
                f"Follow the lifecycle: todo → plan_proposed → plan_approved → in_progress → report_ready.\n"
                f"Use `shux` / `superharness` CLI to advance task status and write handoffs.\n"
                f"Never close a task — only the operator runs `shux close`.\n",
                encoding="utf-8"
            )
        print("Refreshed: GEMINI.md" if opts.refresh else "Created: GEMINI.md")
    else:
        print("Skipped: GEMINI.md (user-owned — use --force to overwrite)")

    # SOUL.md
    soul_dst = Path(project_dir) / "SOUL.md"
    if not soul_dst.exists() or _overwrite_user_file:
        soul_tmpl = template_dir / "SOUL.md.template"
        if soul_tmpl.is_file():
            _render_template(soul_tmpl, soul_dst, project_name, tech_stack, status, project_dir, today)
        else:
            soul_dst.write_text(
                f"# Soul — {project_name}\n\n"
                f"## Operating Constraints\n"
                f"- Ship > plan. One focused task per session.\n"
                f"- Keep changes within the current contract scope.\n\n"
                f"## Guardrails\n"
                f"- Never edit .env, credentials, or secrets.\n"
                f"- Never push directly to main without human review.\n"
                f"- Run required checks before handoff or commit.\n",
                encoding="utf-8"
            )
        print("Refreshed: SOUL.md" if opts.refresh else "Created: SOUL.md")
    else:
        print("Skipped: SOUL.md (user-owned — use --force to overwrite)")

    # Install watcher (macOS only) — runs for both fresh init and --refresh
    _SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
    if install_watcher and platform.system() == "Darwin":
        ensure_script = str(_SCRIPTS / "ensure-launchd-inbox-watcher.sh")
        if os.path.isfile(ensure_script):
            r = subprocess.run(["bash", ensure_script, "--project", project_dir],
                               capture_output=True, text=True)
            if r.returncode == 0:
                print("Watcher: launchd inbox watcher is configured.")
            else:
                print("Watcher: unable to auto-configure (non-fatal).")
                print("  Run manually: shux watcher-worker -p .")
                if r.stderr.strip():
                    print(f"  Detail: {r.stderr.strip()[:200]}")

    # Install Claude Code hooks into ~/.claude/settings.json — runs for both fresh init and --refresh
    if not opts.skip_hooks:
        try:
            from superharness.commands.install_hooks import install_hooks
            install_hooks()
            print("Hooks: ~/.claude/settings.json updated with superharness hooks.")
        except Exception as exc:
            print(f"Hooks: auto-install failed ({exc}). Run manually: shux install-hooks")
    else:
        print("Hooks: skipped (--skip-hooks)")

    if opts.refresh:
        print()
        print("Done. Templates refreshed.")
        return

    # Copy profile.yaml into .superharness/
    if opts.from_profile and os.path.isfile(opts.from_profile):
        shutil.copy2(opts.from_profile, str(harness / "profile.yaml"))
        print(f"Created: .superharness/profile.yaml (from {opts.from_profile})")

    # Patch contract goal for interactive mode
    if interactive_goal:
        import re
        contract_path = harness / "contract.yaml"
        if contract_path.is_file():
            text = contract_path.read_text(encoding="utf-8")
            text = re.sub(r'^goal:.*$', f'goal: "{interactive_goal}"', text, flags=re.MULTILINE)
            contract_path.write_text(text, encoding="utf-8")

    # Clean up interactive temp profile
    if tmp_profile and os.path.isfile(tmp_profile):
        os.unlink(tmp_profile)

    print()
    print("Done. Project initialized with superharness.")
    print()
    print("Directory structure:")
    print("  .superharness/")
    print("  ├── contract.yaml       ← edit this with your first task")
    print("  ├── contracts/           ← completed contracts archive")
    print("  ├── handoffs/            ← agent handoff files")
    print("  ├── review-lenses/       ← project-specific lenses (optional)")
    print("  ├── features.json        ← project feature tracking (passes: false→true only)")
    print("  ├── failures.yaml        ← cross-agent failure memory")
    print("  ├── decisions.yaml       ← cross-agent decision records")
    print("  └── ledger.md            ← append-only activity log")
    print()
    print("Inside Claude Code or Codex CLI, type:")
    print("  shux doctor            ← verify setup")
    print("  shux contract          ← see all tasks")
    print("  shux continue          ← resume active work")
    print("  shux delegate <id>     ← hand off a task")
    print("  shux close <id>        ← mark task done")
    print("  shux status            ← dashboard")
    print("  shux recall <keywords> ← search past work")
    print("  shux dashboard         ← open browser dashboard")
    print()
    print("Enhance agent orientation files with native /init commands:")
    print("  Claude Code: /init     ← rewrites CLAUDE.md with codebase analysis")
    print("  Codex CLI:   /init     ← rewrites AGENTS.md with project context")
    print("  Gemini CLI:  /init     ← rewrites GEMINI.md with project analysis")
    print()
    print("Next steps (terminal):")
    print("  superharness doctor --project .   ← verify setup")
    print('  superharness task create --project . --id my-task --title "..." --owner codex-cli')
    print("  .superharness/.gitignore already created — runtime state excluded, protocol files tracked")
    print()
    if platform.system() != "Darwin":
        print("Tip: To enable a background watcher (macOS only), re-run with --with-watcher")
        print("     or use: superharness watch --foreground --project . --interval 30")

    # Plugin install hint: auto-context in Claude Code requires the plugin
    _home = Path(os.environ["HOME"]) if "HOME" in os.environ else Path.home()
    plugin_path = _home / ".claude" / "plugins" / "superharness"
    if not plugin_path.exists():
        adapter_install = _ROOT / "adapters" / "claude-code" / "install.sh"
        if adapter_install.exists():
            print()
            print("⚡ To enable auto-context in Claude Code, install the plugin once:")
            print(f"   bash {adapter_install}")
            print("   This makes Claude see your task context automatically on every session start.")
    print()
    print("→ Next: run 'shux doctor' to verify your setup, then 'shux dashboard' to open the dashboard.")
    print()
    print("Dashboard: http://127.0.0.1:8787  (start with: shux dashboard)")


if __name__ == "__main__":
    main()
