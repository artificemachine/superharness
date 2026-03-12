from __future__ import annotations

"""Tests for profile.yaml wiring into delegate.sh, task.sh, and contract-today.sh — Phase 1c"""

from pathlib import Path

import pytest

from tests.helpers import run_bash, run_cmd, REPO_ROOT


# ── helpers ───────────────────────────────────────────────────────────────────

def _setup_project(tmp_path: Path, *, owner: str = "codex-cli") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: test-contract",
                "tasks:",
                f"  - id: task-1",
                f"    owner: {owner}",
                "    status: todo",
                f'    project_path: "{project}"',
            ]
        )
        + "\n"
    )
    return project


def _write_profile(harness_dir: Path, **fields) -> None:
    harness_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for k, v in fields.items():
        if isinstance(v, str):
            lines.append(f"{k}: '{v}'")
        else:
            lines.append(f"{k}: {v}")
    (harness_dir / "profile.yaml").write_text("\n".join(lines) + "\n")


def _fake_bin(tmp_path: Path, *names: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in names:
        binary = bin_dir / name
        binary.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\"\n")
        binary.chmod(0o755)
    return bin_dir


# ── delegate.sh: autonomy → env vars ─────────────────────────────────────────

def test_delegate_autonomous_sets_both_env_vars(repo_root, tmp_path) -> None:
    """autonomy=autonomous sets SUPERHARNESS_CONFIRM_NON_INTERACTIVE and CONFIRM_SKIP_PERMISSIONS."""
    project = _setup_project(tmp_path)
    _write_profile(project / ".superharness", autonomy="autonomous")
    bin_dir = _fake_bin(tmp_path, "codex")

    result = run_bash(
        repo_root / "scripts" / "delegate.sh",
        cwd=repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "task-1", "--non-interactive"],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            # Clear these so profile controls them
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": None,
            "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS": None,
        },
    )
    # autonomous sets CONFIRM_NON_INTERACTIVE=YES, so non-interactive proceeds
    # (codex runs without the "refusing" error)
    assert result.returncode == 0, f"Expected success, stderr:\n{result.stderr}"


def test_delegate_supervised_sets_non_interactive_only(repo_root, tmp_path) -> None:
    """autonomy=supervised only sets SUPERHARNESS_CONFIRM_NON_INTERACTIVE (not skip-permissions)."""
    project = _setup_project(tmp_path)
    _write_profile(project / ".superharness", autonomy="supervised")
    bin_dir = _fake_bin(tmp_path, "claude")

    result = run_bash(
        repo_root / "scripts" / "delegate.sh",
        cwd=repo_root,
        args=["--to", "claude-code", "--project", str(project), "--task", "task-1", "--non-interactive"],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": None,
            "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS": None,
        },
    )
    # supervised sets NON_INTERACTIVE=YES so risk check passes,
    # but SKIP_PERMISSIONS is not set → claude-code should refuse (exit 1)
    assert result.returncode == 1
    assert "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS=YES" in result.stderr


def test_delegate_approval_gated_sets_no_env_vars(repo_root, tmp_path) -> None:
    """autonomy=approval-gated sets neither env var → non-interactive launch is refused."""
    project = _setup_project(tmp_path)
    _write_profile(project / ".superharness", autonomy="approval-gated")
    bin_dir = _fake_bin(tmp_path, "codex")

    result = run_bash(
        repo_root / "scripts" / "delegate.sh",
        cwd=repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "task-1", "--non-interactive"],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": None,
            "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS": None,
        },
    )
    assert result.returncode != 0
    assert "SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES" in result.stderr


def test_delegate_existing_env_not_overridden_by_profile(repo_root, tmp_path) -> None:
    """Existing SUPERHARNESS_CONFIRM_* env vars are not clobbered by profile defaults."""
    project = _setup_project(tmp_path)
    # profile says approval-gated, but caller has explicitly set CONFIRM_NON_INTERACTIVE=YES
    _write_profile(project / ".superharness", autonomy="approval-gated")
    bin_dir = _fake_bin(tmp_path, "codex")

    result = run_bash(
        repo_root / "scripts" / "delegate.sh",
        cwd=repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "task-1", "--non-interactive"],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
            "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS": None,
        },
    )
    # NON_INTERACTIVE check passes (caller set it), skip-permissions not set → codex runs
    # codex-cli non-interactive doesn't require skip-permissions so should succeed
    assert result.returncode == 0, f"Expected success (existing env respected), stderr:\n{result.stderr}"


def test_delegate_no_profile_no_crash(repo_root, tmp_path) -> None:
    """If no profile.yaml exists, delegate.sh still runs without crashing."""
    project = _setup_project(tmp_path)
    # No profile.yaml written
    result = run_bash(
        repo_root / "scripts" / "delegate.sh",
        cwd=repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "task-1", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, f"Crashed without profile:\n{result.stderr}"


# ── task.sh: owner from profile ───────────────────────────────────────────────

def test_task_create_uses_profile_primary_agent_when_no_owner(repo_root, tmp_path) -> None:
    """task create with no --owner picks up primary_agent from profile.yaml."""
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text(
        "id: test-contract\ntasks: []\n"
    )
    _write_profile(harness, primary_agent="claude-code")

    result = run_bash(
        repo_root / "scripts" / "task.sh",
        cwd=repo_root,
        args=["create", "--project", str(project), "--id", "t-profile-1", "--title", "Test task"],
        # No --owner flag; stdin empty so prompt read gets empty → but profile should fill it
        stdin="",
    )
    # Should succeed with owner=claude-code from profile
    assert result.returncode == 0, f"task create failed:\n{result.stderr}\n{result.stdout}"
    contract = (harness / "contract.yaml").read_text()
    assert "claude-code" in contract


def test_task_create_explicit_owner_ignores_profile(repo_root, tmp_path) -> None:
    """Explicit --owner overrides any profile primary_agent."""
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text(
        "id: test-contract\ntasks: []\n"
    )
    _write_profile(harness, primary_agent="claude-code")

    result = run_bash(
        repo_root / "scripts" / "task.sh",
        cwd=repo_root,
        args=[
            "create", "--project", str(project),
            "--id", "t-explicit-1", "--title", "Explicit owner task",
            "--owner", "codex-cli",
        ],
        stdin="",
    )
    assert result.returncode == 0, f"task create failed:\n{result.stderr}"
    contract = (harness / "contract.yaml").read_text()
    assert "codex-cli" in contract


def test_task_create_no_owner_no_profile_prompts_user(repo_root, tmp_path) -> None:
    """No --owner and no profile.yaml → user is prompted; piping an answer works."""
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text(
        "id: test-contract\ntasks: []\n"
    )
    # No profile written

    result = run_bash(
        repo_root / "scripts" / "task.sh",
        cwd=repo_root,
        args=["create", "--project", str(project), "--id", "t-prompt-1", "--title", "Prompted task"],
        # Pipe owner answer via stdin
        stdin="codex-cli\n",
    )
    assert result.returncode == 0, f"task create with stdin prompt failed:\n{result.stderr}"
    contract = (harness / "contract.yaml").read_text()
    assert "codex-cli" in contract


# ── contract-today.sh: team_size gates delegation suggestion ──────────────────

def _setup_contract_today_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text(
        "\n".join([
            "id: ct-contract",
            "goal: Test goal",
            "tasks:",
            "  - id: ct-task-1",
            "    title: A task",
            "    owner: codex-cli",
            "    status: todo",
        ]) + "\n"
    )
    return project


def test_contract_today_solo_no_delegation_suggestion(repo_root, tmp_path) -> None:
    """team_size=solo suppresses the delegation suggestion."""
    project = _setup_contract_today_project(tmp_path)
    _write_profile(project / ".superharness", team_size="solo")

    result = run_bash(
        repo_root / "scripts" / "contract-today.sh",
        cwd=repo_root,
        args=["--project", str(project)],
    )
    assert result.returncode == 0, result.stderr
    assert "Do you want to delegate" not in result.stdout


def test_contract_today_small_shows_delegation_suggestion(repo_root, tmp_path) -> None:
    """team_size=small shows the delegation suggestion."""
    project = _setup_contract_today_project(tmp_path)
    _write_profile(project / ".superharness", team_size="small")

    result = run_bash(
        repo_root / "scripts" / "contract-today.sh",
        cwd=repo_root,
        args=["--project", str(project)],
    )
    assert result.returncode == 0, result.stderr
    assert "Do you want to delegate" in result.stdout


def test_contract_today_no_profile_shows_delegation(repo_root, tmp_path) -> None:
    """No profile.yaml → defaults to non-solo → delegation suggestion still shown (backward compat)."""
    project = _setup_contract_today_project(tmp_path)
    # No profile written — old behavior: delegation suggestion is always shown

    result = run_bash(
        repo_root / "scripts" / "contract-today.sh",
        cwd=repo_root,
        args=["--project", str(project)],
    )
    assert result.returncode == 0, result.stderr
    assert "Do you want to delegate" in result.stdout
