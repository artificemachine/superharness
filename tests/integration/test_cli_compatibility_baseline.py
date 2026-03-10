from __future__ import annotations

from pathlib import Path

from tests.helpers import run_bash, shell_guard_list


HELP_ENTRYPOINTS = [
    "superharness",
    "cli/init.sh",
    "cli/contract-today.sh",
    "cli/doctor.sh",
    "cli/install-wrapper.sh",
    "cli/delegate.sh",
    "cli/delegate-task.sh",
    "cli/task.sh",
    "cli/enqueue.sh",
    "cli/dispatch.sh",
    "cli/watch.sh",
    "cli/recover.sh",
    "cli/normalize.sh",
    "cli/hygiene.sh",
]


def test_entrypoint_help_contract(repo_root: Path) -> None:
    guard_entrypoints = shell_guard_list(repo_root, "--list-entrypoints")
    all_entrypoints = sorted(set(HELP_ENTRYPOINTS + guard_entrypoints))
    assert all_entrypoints, "No entrypoints discovered for help smoke contract"
    usage_required = set(HELP_ENTRYPOINTS)

    for rel_path in all_entrypoints:
        script = repo_root / rel_path
        assert script.exists(), f"Missing entrypoint: {rel_path}"
        result = run_bash(script, cwd=repo_root, args=["--help"])
        assert result.returncode == 0, f"{rel_path} --help failed: {result.stderr}"
        if rel_path in usage_required:
            assert "Usage:" in result.stdout, f"{rel_path} --help missing Usage output"
