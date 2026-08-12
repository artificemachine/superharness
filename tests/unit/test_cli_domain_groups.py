"""TDD coverage for executable progressive CLI domains."""

from __future__ import annotations

from unittest.mock import patch

import click
from click.testing import CliRunner

from superharness.cli import main


DOMAIN_COMMANDS = {
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

CORE_COMMANDS = {
    "onboard", "task", "contract", "delegate", "status", "context", "verify",
    "close", "dashboard", "doctor", "recall", "explain",
}
COMPAT_ALIASES = {"discussion", "monitor", "monitor-ui"}


def test_each_domain_forwards_to_canonical_callbacks() -> None:
    context = click.Context(main)

    for domain_name, commands in DOMAIN_COMMANDS.items():
        domain = main.get_command(context, domain_name)
        assert domain is not None, domain_name
        for child_name, canonical_name in commands.items():
            assert domain.get_command(context, child_name) is main.commands[canonical_name]


def test_each_non_core_command_has_exactly_one_domain() -> None:
    grouped = [command for commands in DOMAIN_COMMANDS.values() for command in commands.values()]
    canonical = set(main.commands) - CORE_COMMANDS - COMPAT_ALIASES - {"help", *DOMAIN_COMMANDS}

    assert len(grouped) == len(set(grouped))
    assert set(grouped) == canonical


def test_top_level_and_grouped_paths_have_argument_parity() -> None:
    runner = CliRunner()
    calls: list[tuple[str, tuple[str, ...]]] = []

    def record(module: str, args: tuple[str, ...]) -> None:
        calls.append((module, args))

    samples = [
        (["backup-state", "backup", "--project", "demo"], ["state", "backup", "backup", "--project", "demo"]),
        (["adapters", "list"], ["agent", "adapters", "list"]),
        (["logs", "--tail"], ["ops", "logs", "--tail"]),
        (["distill", "--dry-run"], ["memory", "distill", "--dry-run"]),
    ]

    with patch("superharness.cli._run_module", side_effect=record):
        for top_level, grouped in samples:
            assert runner.invoke(main, top_level).exit_code == 0
            assert runner.invoke(main, grouped).exit_code == 0

    assert calls[::2] == calls[1::2]


def test_domain_help_is_scoped() -> None:
    runner = CliRunner()

    for name, commands in DOMAIN_COMMANDS.items():
        result = runner.invoke(main, [name, "--help"])
        assert result.exit_code == 0, result.output
        for child_name in commands:
            assert child_name in result.output
