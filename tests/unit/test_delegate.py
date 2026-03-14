from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.helpers import REPO_ROOT, run_bash


def _run_delegate_py(cwd, args: list[str] | None = None, env: dict | None = None):
    """Run delegate Python module."""
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(REPO_ROOT / "src")
    if env:
        for k, v in env.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
    cmd = [sys.executable, "-m", "superharness.commands.delegate"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=merged, check=False)


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: test-contract",
                "tasks:",
                "  - id: mcp-docs",
                "    owner: codex-cli",
                "    status: todo",
                f'    project_path: "{project}"',
            ]
        )
        + "\n"
    )
    return project


def _fake_bin(tmp_path: Path, *names: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in names:
        binary = bin_dir / name
        binary.write_text(f"#!/bin/bash\necho fake-{name}\n")
        binary.chmod(0o755)
    return bin_dir


def test_delegate_print_only_does_not_require_target_cli(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)

    # Use a minimal PATH that does not include user-installed codex/claude CLIs.
    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Generated prompt:" in result.stdout
    assert "execute task mcp-docs" in result.stdout


def test_delegate_claude_non_interactive_requires_specific_skip_permissions_confirmation(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    bin_dir = _fake_bin(tmp_path, "claude")

    result = _run_delegate_py(
        repo_root,
        args=["--to", "claude-code", "--project", str(project), "--task", "mcp-docs", "--non-interactive"],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )

    assert result.returncode == 1
    assert "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES" in result.stderr


def test_delegate_codex_bypass_requires_specific_confirmation(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    bin_dir = _fake_bin(tmp_path, "codex")

    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--non-interactive", "--codex-bypass"],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )

    assert result.returncode == 1
    assert "SUPERHARNESS_CONFIRM_CODEX_BYPASS=YES" in result.stderr


def test_delegate_surfaces_malformed_handoff_error(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    handoff = project / ".superharness" / "handoffs" / "bad.yaml"
    handoff.write_text(":\n  - invalid\n")

    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project)],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode != 0
    assert "Failed to parse handoff" in result.stderr


def test_delegate_codex_non_interactive_adds_skip_git_repo_check(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    codex = bin_dir / "codex"
    codex.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\"\n")
    codex.chmod(0o755)

    result = _run_delegate_py(
        repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--non-interactive"],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "--skip-git-repo-check" in result.stdout
    assert "--full-auto" in result.stdout
