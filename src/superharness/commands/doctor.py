"""doctor command — check local setup and project protocol health."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys


def _install_hint(dep: str) -> str:
    is_mac = platform.system() == "Darwin"
    hints = {
        "python3": "brew install python3" if is_mac else "sudo apt install python3   # or: sudo dnf install python3",
        "claude": "npm i -g @anthropic-ai/claude-code",
        "codex": "npm i -g @openai/codex",
    }
    return hints.get(dep, "")


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="doctor")
    p.add_argument("-p", "--project", default=os.getcwd())
    p.add_argument("--check", action="store_true")
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

    for fname in ("contract.yaml", "ledger.md", "decisions.yaml", "failures.yaml"):
        fpath = os.path.join(harness_dir, fname)
        if os.path.isfile(fpath):
            print(f"PASS file:{fname}")
        else:
            print(f"FAIL file:{fname} missing")
            print("       Re-initialize: superharness init")
            failures += 1

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
                print(f"WARN git:core.hooksPath={hooks_path}")
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
            print("       The background watcher is required — would you like to install it? (run: bash scripts/install-launchd-inbox-watcher.sh --project .)")
            print("       Or use foreground mode instead: superharness watch --foreground --project .")
            warns += 1
    elif sys_platform == "Linux":
        print("INFO watcher:launchd not available (non-macOS)")
        print("       Use foreground mode: superharness watch --foreground --project .")
    else:
        print(f"INFO watcher:platform {sys_platform} — use foreground mode: superharness watch --foreground --project .")

    print(f"summary: failures={failures} warnings={warns}")
    if failures > 0:
        print()
        print("→ Fix the failures above, then re-run 'shux doctor'.")
        sys.exit(1)
    if opts.check and warns > 0:
        sys.exit(1)
    print()
    print("→ Next: run 'shux contract' to see your tasks, or 'shux monitor' to open the dashboard.")


if __name__ == "__main__":
    main()
