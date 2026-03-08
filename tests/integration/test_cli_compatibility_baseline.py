from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import run_bash


HELP_ENTRYPOINTS = [
    "init-project.sh",
    "scripts/delegate-to-claude.sh",
    "scripts/delegate-to-codex.sh",
    "scripts/inbox-enqueue.sh",
    "scripts/inbox-dispatch.sh",
    "scripts/inbox-watch.sh",
    "scripts/inbox-normalize.sh",
    "scripts/check-contract-hygiene.sh",
    "scripts/install-launchd-inbox-watcher.sh",
    "scripts/ensure-launchd-inbox-watcher.sh",
    "scripts/uninstall-launchd-inbox-watcher.sh",
    "scripts/install-git-hooks.sh",
    "adapters/claude-code/install.sh",
]


@pytest.mark.parametrize("rel_path", HELP_ENTRYPOINTS)
def test_entrypoint_help_contract(repo_root: Path, rel_path: str) -> None:
    script = repo_root / rel_path
    assert script.exists(), f"Missing entrypoint: {rel_path}"
    result = run_bash(script, cwd=repo_root, args=["--help"])
    assert result.returncode == 0, f"{rel_path} --help failed: {result.stderr}"
    assert "Usage:" in result.stdout, f"{rel_path} --help missing Usage output"
