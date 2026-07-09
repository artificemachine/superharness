"""Worktree garbage collector — clean orphaned dispatch worktrees."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


WORKTREE_BASE = os.path.join(tempfile.gettempdir(), "superharness-worktrees")


def _git_common_dir(path: str) -> str | None:
    """Absolute git common dir (the main repo's .git) for *path*, or None if
    *path* is not a live git worktree."""
    r = subprocess.run(
        ["git", "-C", path, "rev-parse", "--git-common-dir"],
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return None
    common = r.stdout.strip()
    if not os.path.isabs(common):
        common = os.path.join(path, common)
    try:
        return os.path.realpath(common)
    except OSError:
        return None


def run_worktree_gc(project_dir: str | Path, dry_run: bool = False) -> dict:
    """Remove orphaned dispatch worktrees. Returns summary dict."""
    project_dir = Path(project_dir).resolve()

    if not os.path.isdir(WORKTREE_BASE):
        print("No worktree directory found — nothing to clean.")
        return {"removed": 0, "kept": 0, "items": []}

    # Get active worktrees known to git
    active_worktrees: set[str] = set()
    r = subprocess.run(
        ["git", "-C", str(project_dir), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, check=False,
    )
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            if line.startswith("worktree "):
                active_worktrees.add(line.split(" ", 1)[1].strip())

    # WORKTREE_BASE is shared by every superharness project on this machine,
    # but active_worktrees only covers THIS project. Resolve which repo each
    # entry belongs to so we never delete another project's live worktree.
    our_common = _git_common_dir(str(project_dir))

    removed = 0
    kept = 0
    items = []

    for entry in sorted(os.listdir(WORKTREE_BASE)):
        wt_path = os.path.join(WORKTREE_BASE, entry)
        if not os.path.isdir(wt_path):
            continue

        owner_common = _git_common_dir(wt_path)
        if owner_common is not None and owner_common != our_common:
            # Live worktree of a different repo/project — leave it alone.
            kept += 1
            items.append({"path": entry, "action": "kept", "reason": "other project"})
            continue

        is_active = wt_path in active_worktrees

        if is_active:
            kept += 1
            items.append({"path": entry, "action": "kept", "reason": "active worktree"})
            continue

        if dry_run:
            removed += 1
            items.append({"path": entry, "action": "would_remove", "reason": "orphaned"})
            print(f"[dry-run] would remove: {entry}")
        else:
            # Remove symlink first if present
            harness_link = os.path.join(wt_path, ".superharness")
            if os.path.islink(harness_link):
                os.unlink(harness_link)
            # Try git worktree remove first
            rr = subprocess.run(
                ["git", "-C", str(project_dir), "worktree", "remove", "--force", wt_path],
                capture_output=True, text=True, check=False,
            )
            if rr.returncode != 0:
                # Fallback: rm -rf
                shutil.rmtree(wt_path, ignore_errors=True)
            removed += 1
            items.append({"path": entry, "action": "removed", "reason": "orphaned"})
            print(f"Removed: {entry}")

    # Prune git worktree references
    if not dry_run and removed > 0:
        subprocess.run(
            ["git", "-C", str(project_dir), "worktree", "prune"],
            capture_output=True, check=False,
        )

    print(f"\nWorktree GC: {removed} removed, {kept} kept")
    return {"removed": removed, "kept": kept, "items": items}


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="worktree-gc",
        description="Clean orphaned dispatch worktrees",
    )
    parser.add_argument("--project", "-p", default=None)
    parser.add_argument("--dry-run", action="store_true", default=False)
    opts = parser.parse_args(argv)

    project = os.path.realpath(opts.project or os.getcwd())
    run_worktree_gc(project, dry_run=opts.dry_run)


if __name__ == "__main__":
    main()
