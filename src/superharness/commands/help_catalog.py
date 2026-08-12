"""The public command-discovery taxonomy for the superharness CLI."""

from __future__ import annotations

import os
from pathlib import Path

CORE_COMMANDS: tuple[str, ...] = (
    "onboard",
    "task",
    "contract",
    "delegate",
    "status",
    "context",
    "verify",
    "close",
    "dashboard",
    "doctor",
    "recall",
    "explain",
)

DOMAIN_ENTRY_POINTS: dict[str, str] = {
    "state": "Project state, configuration, backups, and compatibility.",
    "agent": "Agent adapters, dispatch, collaboration, and worktrees.",
    "ops": "Daemons, dashboard operations, diagnostics, and integrations.",
    "memory": "Recall, distilled lessons, profiles, and learned patterns.",
}

# Domain leaf name -> existing top-level command.  The root path remains the
# compatibility path; domain groups only provide a progressive discovery view.
DOMAIN_COMMANDS: dict[str, dict[str, str]] = {
    "state": {
        "approve": "approve",
        "archive": "archive-yaml",
        "artifact": "artifact",
        "backup": "backup-state",
        "config": "config",
        "export": "export-yaml",
        "import": "import-yaml",
        "migrate": "migrate-state",
        "pack": "pack",
        "reject": "reject",
        "rules": "rules",
        "workflow": "workflow",
    },
    "agent": {
        "adapters": "adapters",
        "payload": "adapter-payload",
        "pulse": "pulse",
        "agent-pulse": "agent-pulse",
        "auto-dispatch": "auto-dispatch",
        "benchmark": "benchmark",
        "continue": "continue",
        "discuss": "discuss",
        "dispatch": "dispatch",
        "enqueue": "enqueue",
        "handoff": "handoff",
        "handoff-generate": "handoff-generate",
        "handoff-write": "handoff-write",
        "schedule": "schedule",
        "subtask-cancel": "subtask-cancel",
        "talk": "talk",
        "test-type": "test-type",
        "worktree": "worktree",
        "worktree-gc": "worktree-gc",
    },
    "ops": {
        "daemon": "daemon",
        "dashboard-kill": "dashboard-kill",
        "dashboard-list": "dashboard-list",
        "dashboard-ui": "dashboard-ui",
        "demo": "demo",
        "diff": "diff",
        "enhance": "enhance",
        "heartbeat": "heartbeat",
        "hook": "hook",
        "hygiene": "hygiene",
        "inbox-gc": "inbox-gc",
        "init": "init",
        "install-hooks": "install-hooks",
        "install-wrapper": "install-wrapper",
        "logs": "logs",
        "mcp": "mcp",
        "normalize": "normalize",
        "notify": "notify",
        "notify-desktop": "notify-desktop",
        "observation": "observation",
        "operator": "operator",
        "pipeline-check": "pipeline-check",
        "recover": "recover",
        "run": "run",
        "shux": "shux",
        "tui": "tui",
        "uninstall": "uninstall",
        "update": "update",
        "version": "version",
        "watch": "watch",
        "watcher-worker": "watcher-worker",
    },
    "memory": {
        "distill": "distill",
        "insights": "insights",
        "roots": "memory-roots",
        "forget": "operator-forget",
        "patterns": "operator-memory",
        "profile": "profile",
        "recap": "recap",
    },
}

COMPAT_ALIASES: frozenset[str] = frozenset({"discussion", "monitor", "monitor-ui"})
INTERNAL_COMMANDS: frozenset[str] = frozenset({"help"})
LEGACY_STATE_COMMANDS: frozenset[str] = frozenset(
    {"archive", "export", "import", "migrate"}
)
_LEGACY_STATE_FILES: tuple[str, ...] = (
    "state.sqlite3",
    "contract.yaml",
    "inbox.yaml",
    "failures.yaml",
    "decisions.yaml",
)


def canonical_command_names(commands: dict[str, object]) -> list[str]:
    """Return public top-level command names in stable display order."""
    excluded = COMPAT_ALIASES | INTERNAL_COMMANDS
    return sorted(name for name in commands if name not in excluded)


def legacy_state_present(project_dir: str | Path | None = None) -> bool:
    """Return whether read-only filesystem signals require legacy tooling."""
    root = Path(project_dir or os.environ.get("SUPERHARNESS_PROJECT") or os.getcwd())
    try:
        return any((root / ".superharness" / name).is_file() for name in _LEGACY_STATE_FILES)
    except OSError:
        return False
