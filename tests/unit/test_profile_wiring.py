from __future__ import annotations

"""Tests for profile.yaml wiring into delegate.py, task.sh, and contract-today.sh — Phase 1c"""

import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from tests.helpers import REPO_ROOT, run_bash  # noqa: E402

_skip_win = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


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
    # Pipe an empty string as stdin so sys.stdin.isatty() returns False in the
    # subprocess on all platforms.  subprocess.DEVNULL does NOT work here:
    # Windows treats NUL as a console device and isatty() returns True,
    # causing _confirm_*_risk() to print the interactive prompt instead of the
    # expected "Set <ENV>=YES" refusal message.
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=merged,
        check=False,
        input="",
    )


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
                "  - id: task-1",
                f"    owner: {owner}",
                "    status: plan_approved",
                f"    project_path: '{project.as_posix()}'",
            ]
        )
        + "\n"
    )
    from tests.helpers import seed_sqlite_from_yaml

    seed_sqlite_from_yaml(project)
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
        if sys.platform == "win32":
            # .cmd extension is required for shutil.which() to find the fake
            # binary on Windows (PATHEXT must include .CMD, which it does by default).
            binary = bin_dir / f"{name}.cmd"
            binary.write_text("@echo off\nexit /b 0\n")
        else:
            binary = bin_dir / name
            binary.write_text("#!/bin/bash\nprintf '%s\\n' \"$@\"\n")
            binary.chmod(0o755)
    return bin_dir


def _make_path(bin_dir: Path) -> str:
    """Return a PATH string with bin_dir prepended, platform-aware."""
    # On Windows, prepend to the existing PATH (preserves PATHEXT and system dirs).
    # On Unix, append the two standard system dirs so subprocess calls resolve.
    if sys.platform == "win32":
        return str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    return f"{bin_dir}:/usr/bin:/bin"


# ── delegate.sh: autonomy → env vars ─────────────────────────────────────────






def test_delegate_approval_gated_sets_no_env_vars(repo_root, tmp_path) -> None:
    """autonomy=approval-gated sets neither env var → non-interactive launch is refused."""
    project = _setup_project(tmp_path)
    _write_profile(project / ".superharness", autonomy="approval-gated")
    bin_dir = _fake_bin(tmp_path, "codex")

    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "task-1",
            "--non-interactive",
        ],
        env={
            "PATH": _make_path(bin_dir),
            "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": None,
            "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS": None,
        },
    )
    assert result.returncode != 0
    assert "SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES" in result.stderr




def test_delegate_no_profile_no_crash(repo_root, tmp_path) -> None:
    """If no profile.yaml exists, delegate.py still runs without crashing."""
    project = _setup_project(tmp_path)
    # No profile.yaml written
    result = _run_delegate_py(
        repo_root,
        args=[
            "--to",
            "codex-cli",
            "--project",
            str(project),
            "--task",
            "task-1",
            "--print-only",
        ],
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, f"Crashed without profile:\n{result.stderr}"


# ── task.sh: owner from profile ───────────────────────────────────────────────








# ── contract-today.sh: team_size gates delegation suggestion ──────────────────


def _setup_contract_today_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: ct-contract",
                "goal: Test goal",
                "tasks:",
                "  - id: ct-task-1",
                "    title: A task",
                "    owner: codex-cli",
                "    status: plan_approved",
            ]
        )
        + "\n"
    )
    return project






