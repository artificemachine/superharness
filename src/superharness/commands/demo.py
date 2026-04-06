"""demo command — zero-config task lifecycle walkthrough."""
from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="demo", description="Zero-config superharness task lifecycle walkthrough.")
    p.add_argument("--keep", action="store_true", help="Keep temp directory after demo")
    opts = p.parse_args(argv)

    demo_dir = tempfile.mkdtemp(prefix="superharness-demo-")
    if not opts.keep:
        atexit.register(shutil.rmtree, demo_dir, ignore_errors=True)

    def step(n: str) -> None:
        print()
        print(f"── {n}")

    py = sys.executable
    src_root = Path(__file__).resolve().parent.parent.parent.parent
    env = {**os.environ, "PYTHONPATH": str(src_root / "src")}

    print()
    print("superharness demo — task lifecycle walkthrough")
    print("===============================================")
    print(f"Temp project: {demo_dir}")

    step("1 / 5  init")
    subprocess.run([py, "-m", "superharness.commands.init_project", "--dry-run", "Demo Project", "Bash", "greenfield"],
                   env=env, cwd=demo_dir, check=False)
    subprocess.run([py, "-m", "superharness.commands.init_project", "Demo Project", "Bash", "greenfield"],
                   env=env, cwd=demo_dir, check=False)

    step("2 / 5  task create")
    subprocess.run([py, "-m", "superharness.commands.task", "create",
                    "--project", demo_dir, "--id", "demo-task",
                    "--title", "Hello from superharness demo", "--owner", "codex-cli"],
                   env=env, check=False)

    step("3 / 5  enqueue")
    subprocess.run([py, "-m", "superharness.commands.inbox_enqueue",
                    "--project", demo_dir, "--to", "codex-cli", "--task", "demo-task", "--priority", "1"],
                   env=env, check=False)

    step("4 / 5  dispatch (print-only — no agent CLI needed)")
    subprocess.run([py, "-m", "superharness.commands.inbox_dispatch",
                    "--project", demo_dir, "--to", "codex-cli", "--print-only"],
                   env=env, check=False)

    step("5 / 5  hygiene check")
    subprocess.run([py, "-m", "superharness.engine.validate", "--project", demo_dir],
                   env=env, check=False)

    print()
    print("===============================================")
    print("Demo complete. What just happened:")
    print()
    print("  1. init      Created .superharness/ protocol files")
    print("  2. task      Added 'demo-task' to contract.yaml")
    print("  3. enqueue   Placed task in inbox.yaml queue")
    print("  4. dispatch  Generated the agent prompt (print-only)")
    print("  5. hygiene   Validated protocol state")
    print()
    print("Command-First Workflow (recommended for new users):")
    print("  Just type these commands directly to your AI agent:")
    print()
    print("    shux init              # Start here")
    print("    shux doctor            # Check health")
    print("    shux contract          # View tasks")
    print("    shux delegate <id>     # Dispatch a task")
    print()
    print("Next steps to try on a real project:")
    print('  cd /your/project')
    print('  shux init "My Project" "Python" "active"')
    print("  shux doctor")
    print("  shux dashboard         # browser dashboard")
    print()
    print("To run real (non-print-only) dispatch you'll need an agent CLI:")
    print("  Claude Code:  npm install -g @anthropic-ai/claude-code")  # shipguard:ignore SC-003
    print("  Codex CLI:    npm install -g @openai/codex")  # shipguard:ignore SC-003
    print()
    print("Full guide: docs/GUIDE.md")

    if opts.keep:
        print()
        print(f"Demo directory kept at: {demo_dir}")


if __name__ == "__main__":
    main()
