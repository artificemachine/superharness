"""demo command — zero-config task lifecycle walkthrough."""
from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import click


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="demo", description="Zero-config superharness task lifecycle walkthrough.")
    p.add_argument("--keep", action="store_true", help="Keep temp directory after demo")
    p.add_argument("--no-interactive", action="store_false", dest="interactive", help="Disable interactive mode (pauses)")
    p.set_defaults(interactive=True)
    opts = p.parse_args(argv)

    demo_dir = tempfile.mkdtemp(prefix="superharness-demo-")
    if not opts.keep:
        atexit.register(shutil.rmtree, demo_dir, ignore_errors=True)

    def step(n: int, title: str, description: str = "") -> None:
        print()
        click.secho(f"── Step {n} / 17: {title}", fg="cyan", bold=True)
        if description:
            click.echo(f"   {description}")
        sys.stdout.flush()

    def pause_after() -> None:
        if opts.interactive:
            click.pause(info=click.style("   [Press any key to continue...]", fg="bright_black"))

    py = sys.executable
    src_root = Path(__file__).resolve().parent.parent.parent.parent
    env = {**os.environ, "PYTHONPATH": str(src_root / "src")}

    print()
    click.secho("superharness — interactive walkthrough", fg="green", bold=True)
    click.echo("======================================")
    click.echo()
    click.echo("  This demo will walk you through the full task lifecycle in a")
    click.echo("  temporary project. No real agent or API keys required.")
    click.echo()
    click.echo(f"  Temp project: {demo_dir}")

    # 1. Explain
    step(1, "Explain", "The 10-second pitch: what is this and why does it exist?")
    subprocess.run([py, "-m", "superharness.commands.explain"], env=env, check=False)
    pause_after()

    # 2. Init Preview
    step(2, "Init Preview", "Safety first: see what 'init' would do before it does it.")
    subprocess.run([py, "-m", "superharness.commands.init_project", "--dry-run", "--skip-hooks",
                    "Demo Project", "Bash", "greenfield"],
                   env=env, cwd=demo_dir, check=False)
    pause_after()

    # 3. Init — scaffold dirs + database only (the hidden infrastructure)
    step(3, "Init: Scaffold", "Creating .superharness/ directories and the SQLite state database.")
    result = subprocess.run(
        [py, "-m", "superharness.commands.init_project", "--skip-hooks", "Demo Project", "Bash", "greenfield"],
        env=env, cwd=demo_dir, capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Created:") or stripped.startswith(".superharness") or stripped.startswith("├") or stripped.startswith("└") or stripped.startswith("│"):
            click.echo(line)
    pause_after()

    # 4. Init — show generated CLAUDE.md (agent instructions)
    step(4, "Init: CLAUDE.md", "Inspect the agent instruction file init just generated.")
    claude_md = Path(demo_dir) / "CLAUDE.md"
    if claude_md.exists():
        click.echo(claude_md.read_text())
    else:
        click.echo("   (CLAUDE.md not found — init may have skipped it for an existing file)")
    pause_after()

    # 5. Init — show generated AGENTS.md (cross-agent protocol rules)
    step(5, "Init: AGENTS.md", "Inspect the cross-agent protocol rules init just generated.")
    agents_md = Path(demo_dir) / "AGENTS.md"
    if agents_md.exists():
        click.echo(agents_md.read_text())
    else:
        click.echo("   (AGENTS.md not found — init may have skipped it for an existing file)")
    pause_after()

    # 6. Inspect
    step(6, "Inspect", "Full directory tree: every protocol artifact now in place.")
    subprocess.run(["ls", "-R", ".superharness"], env=env, cwd=demo_dir, check=False)
    pause_after()

    # 7. Task Create
    step(7, "Task Create", "Defining a unit of work with clear ownership.")
    subprocess.run([py, "-m", "superharness.commands.task", "create",
                    "--project", demo_dir, "--id", "demo-task",
                    "--title", "Implement a simple hello world script", "--owner", "codex-cli"],
                   env=env, check=False)
    pause_after()

    # 8. Contract
    step(8, "Contract", "The single source of truth for every task in the project.")
    subprocess.run([py, "-m", "superharness.commands.contract_today", "--project", demo_dir], env=env, check=False)
    pause_after()

    # 9. Enqueue
    step(9, "Enqueue", "Placing the task in the inbox queue for an agent to pick up.")
    subprocess.run([py, "-m", "superharness.commands.inbox_enqueue",
                    "--project", demo_dir, "--to", "codex-cli", "--task", "demo-task", "--priority", "1"],
                   env=env, check=False)
    pause_after()

    # 10. Status
    step(10, "Status", "Checking the health of the inbox, watcher, and tasks.")
    subprocess.run([py, "-m", "superharness.commands.status", "--project", demo_dir], env=env, check=False)
    pause_after()

    # 11. Dispatch (Print-only)
    step(11, "Dispatch", "Generating the exact prompt that guides the AI agent.")
    subprocess.run([py, "-m", "superharness.commands.inbox_dispatch",
                    "--project", demo_dir, "--to", "codex-cli", "--print-only"],
                   env=env, check=False)
    pause_after()

    # 12. Plan Handoff
    step(12, "Plan Handoff", "Agents must propose a plan before implementation.")
    subprocess.run([py, "-m", "superharness.commands.handoff_write",
                    "--project", demo_dir, "--task", "demo-task", "--phase", "plan",
                    "--from", "codex-cli", "--status", "plan_proposed",
                    "--plan", "I will create hello.sh and add a print statement.",
                    "--tdd-red", "Script should exist", "--tdd-green", "Run script"],
                   env=env, check=False)
    pause_after()

    # 13. Approve
    step(13, "Approve", "Governance: the operator approves the plan to allow implementation.")
    subprocess.run([py, "-m", "superharness.commands.approve", "--project", demo_dir, "--id", "demo-task"],
                   env=env, check=False)
    pause_after()

    # 14. Report Handoff
    step(14, "Report Handoff", "Agent reports completion, providing evidence and context.")
    subprocess.run([py, "-m", "superharness.commands.handoff_write",
                    "--project", demo_dir, "--task", "demo-task", "--phase", "report",
                    "--from", "codex-cli", "--status", "report_ready",
                    "--outcome", "Created hello.sh and verified output."],
                   env=env, check=False)
    pause_after()

    # 15. Verify
    step(15, "Verify", "Quality gate: recording a passing verification result.")
    subprocess.run([py, "-m", "superharness.commands.verify",
                    "--project", demo_dir, "--id", "demo-task", "--method", "manual run", "--result", "pass"],
                   env=env, check=False)
    pause_after()

    # 16. Close
    step(16, "Close", "Closing the task: archiving state and updating the ledger.")
    subprocess.run([py, "-m", "superharness.commands.close", "--project", demo_dir, "--id", "demo-task"],
                   env=env, check=False)
    pause_after()

    # 17. Recap
    step(17, "Recap", "Session history: what happened across the multi-agent workflow?")
    subprocess.run([py, "-m", "superharness.commands.recap", "--project", demo_dir, "--hours", "1"],
                   env=env, check=False)

    print()
    click.secho("======================================", fg="green", bold=True)
    click.echo("Demo complete! You've seen the full multi-agent lifecycle.")
    click.echo()
    click.echo("Next steps to try on a real project:")
    click.echo('  cd /your/project')
    click.echo('  shux onboard           # Interactive setup wizard')
    click.echo("  shux doctor            # Check your environment")
    click.echo("  shux dashboard         # Launch the browser UI")
    click.echo()
    click.echo("Full guide: docs/GUIDE.md")

    if opts.keep:
        print()
        click.echo(f"Demo directory kept at: {demo_dir}")


if __name__ == "__main__":
    main()
