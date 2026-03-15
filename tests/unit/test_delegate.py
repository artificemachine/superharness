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


def _setup_project(tmp_path: Path, extra_task_fields: str = "") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    task_block = "\n".join(
        [
            "id: test-contract",
            "tasks:",
            "  - id: mcp-docs",
            "    owner: codex-cli",
            "    status: todo",
            f'    project_path: "{project}"',
        ]
    )
    if extra_task_fields:
        task_block += "\n" + extra_task_fields
    (harness / "contract.yaml").write_text(task_block + "\n")
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


# ---------------------------------------------------------------------------
# Model routing tests
# ---------------------------------------------------------------------------


def test_delegate_print_only_shows_model_and_effort(repo_root, tmp_path) -> None:
    """--print-only output includes Model: and Effort: lines."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "codex-cli", "--project", str(project),
            "--task", "mcp-docs", "--print-only", "--no-auto-model",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Model:" in result.stdout
    assert "Effort:" in result.stdout


def test_delegate_model_override_via_cli(repo_root, tmp_path) -> None:
    """--model flag overrides auto-classification."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "claude-code", "--project", str(project),
            "--task", "mcp-docs", "--print-only",
            "--model", "opus", "--effort", "high",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Model: opus (manual)" in result.stdout
    assert "Effort: high" in result.stdout


def test_delegate_no_auto_model_uses_fallback(repo_root, tmp_path) -> None:
    """--no-auto-model skips classification and falls back to standard/medium."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "claude-code", "--project", str(project),
            "--task", "mcp-docs", "--print-only", "--no-auto-model",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Model: sonnet (fallback)" in result.stdout
    assert "Effort: medium" in result.stdout


def test_delegate_task_level_model_field(repo_root, tmp_path) -> None:
    """model field on a task in contract.yaml is used when no CLI flag."""
    project = _setup_project(tmp_path, extra_task_fields="    model: mini\n    effort: low")

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "claude-code", "--project", str(project),
            "--task", "mcp-docs", "--print-only", "--no-auto-model",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    # mini resolves to haiku for claude-code
    assert "Model: haiku (task)" in result.stdout
    assert "Effort: low" in result.stdout


def test_delegate_tier_name_resolves_to_agent_model(repo_root, tmp_path) -> None:
    """Passing --model max resolves to opus for claude-code."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "claude-code", "--project", str(project),
            "--task", "mcp-docs", "--print-only",
            "--model", "max",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Model: opus (manual)" in result.stdout


def test_delegate_codex_tier_resolves_correctly(repo_root, tmp_path) -> None:
    """Passing --model mini resolves to gpt-5.2 for codex-cli."""
    project = _setup_project(tmp_path)

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to", "codex-cli", "--project", str(project),
            "--task", "mcp-docs", "--print-only",
            "--model", "mini",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Model: gpt-5.2 (manual)" in result.stdout
