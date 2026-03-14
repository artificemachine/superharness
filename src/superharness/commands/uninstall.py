"""uninstall command — remove system-level superharness artifacts."""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="uninstall")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--all", action="store_true", dest="all_")
    opts = p.parse_args(argv)

    removed = 0
    is_tty = sys.stdin.isatty()

    def action(label: str, path: str, kind: str) -> None:
        nonlocal removed
        if opts.dry_run:
            print(f"[dry-run] Would remove {kind}: {path} ({label})")
            removed += 1
            return
        if opts.all_:
            confirm = "y"
        elif is_tty:
            confirm = input(f"Remove {kind}: {path} ({label})? [y/N] ").strip().lower()
        else:
            print(f"Skipped (non-interactive, use --all to force): {path}")
            return
        if confirm == "y":
            if kind == "file" and os.path.isfile(path):
                os.remove(path)
                print(f"Removed: {path}")
                removed += 1
            elif kind == "dir" and os.path.isdir(path):
                shutil.rmtree(path)
                print(f"Removed: {path}")
                removed += 1
        else:
            print(f"Skipped: {path}")

    print("superharness uninstall")
    print("======================")
    print()

    # 1. Remove launchd plists (macOS only)
    launch_agents = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")
    if os.path.isdir(launch_agents):
        for plist in sorted(glob.glob(os.path.join(launch_agents, "com.superharness.inbox.*.plist"))):
            label = os.path.splitext(os.path.basename(plist))[0]
            if not opts.dry_run:
                uid = os.getuid() if hasattr(os, "getuid") else 0
                subprocess.run(
                    ["launchctl", "bootout", f"gui/{uid}/{label}"],
                    capture_output=True
                )
            else:
                print(f"[dry-run] Would unload launchd service: {label}")
            action("launchd plist", plist, "file")

    # 2. Remove watcher logs
    log_dir = os.path.join(os.path.expanduser("~"), "Library", "Logs", "superharness")
    if os.path.isdir(log_dir):
        action("watcher logs", log_dir, "dir")

    # 3. Remove wrapper symlink
    wrapper = os.path.join(os.path.expanduser("~"), ".local", "bin", "superharness")
    if os.path.islink(wrapper):
        action("wrapper symlink", wrapper, "file")

    # 4. Remove watcher lock files
    for lockdir in sorted(glob.glob("/tmp/superharness-inbox-watch-*.lock")):
        if os.path.isdir(lockdir):
            action("watcher lock", lockdir, "dir")

    print()
    if removed == 0:
        print("Nothing to remove.")
    elif opts.dry_run:
        print(f"Dry run complete. {removed} item(s) would be removed.")
    else:
        print(f"Removed {removed} item(s).")

    print()
    print("=" * 56)
    print("IMPORTANT: Per-project state is NOT removed.")
    print()
    print("  .superharness/ directories inside your projects are")
    print("  intentionally preserved — they contain your contract,")
    print("  handoffs, ledger, and failure memory.")
    print()
    print("  To remove a project's state:")
    print("    rm -rf /path/to/project/.superharness")
    print()
    print("  To remove Claude Code hooks:")
    print("    Edit ~/.claude/settings.json and delete the")
    print("    superharness entries under 'hooks'.")
    print("=" * 56)


if __name__ == "__main__":
    main()
