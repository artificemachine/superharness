"""CLI for agent memory management — shux memory roots <add|list|remove>."""
from __future__ import annotations

import sys


def cmd_memory_roots(args: list[str]) -> None:
    """Manage project root directories for cross-project memory scanning.

    Usage:
      shux memory roots list              — show configured project roots
      shux memory roots add <path>        — add a directory to scan
      shux memory roots remove <path>     — remove a directory
    """
    from superharness.engine.agent_memory import (
        list_project_roots, add_project_root, remove_project_root,
    )

    if not args or args[0] == "list":
        roots = list_project_roots()
        if roots:
            print("Project roots (scanned for cross-project memory):")
            for r in roots:
                print(f"  {r}")
        else:
            print("No project roots configured.")
            print("Add one:  shux memory roots add ~/projects")
        return

    subcmd = args[0]
    if subcmd == "add" and len(args) >= 2:
        path = args[1]
        if add_project_root(path):
            print(f"Added: {path}")
        else:
            print(f"Error: '{path}' is not a valid directory or already added", file=sys.stderr)
            sys.exit(1)
    elif subcmd == "remove" and len(args) >= 2:
        path = args[1]
        if remove_project_root(path):
            print(f"Removed: {path}")
        else:
            print(f"Error: '{path}' is not in the project roots list", file=sys.stderr)
            sys.exit(1)
    else:
        print("Usage: shux memory roots <list|add|remove> [path]")
        sys.exit(1)
