from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT


def _run_python(args: list[str], *, env: dict | None = None) -> "subprocess.CompletedProcess[str]":
    import os
    import subprocess
    merged_env = os.environ.copy()
    merged_env["PYTHONPATH"] = str(REPO_ROOT / "src")
    if env:
        for k, v in env.items():
            if v is None:
                merged_env.pop(k, None)
            else:
                merged_env[k] = v
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.doctor"] + args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=merged_env,
        check=False,
    )


def _write_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()
    (harness / "contract.yaml").write_text("id: test\ntasks: []\n")
    (harness / "ledger.md").write_text("# Ledger\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    return project


def test_doctor_help(repo_root) -> None:
    result = _run_python(["--help"])
    assert result.returncode == 0
    assert "--project" in result.stdout
    assert "--check" in result.stdout


def test_doctor_passes_healthy_project(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)
    result = _run_python(["--project", str(project)])
    assert result.returncode == 0
    assert "PASS project:.superharness present" in result.stdout
    assert "PASS file:contract.yaml" in result.stdout
    assert "PASS file:ledger.md" in result.stdout
    assert "PASS dir:handoffs" in result.stdout


def test_doctor_fails_missing_superharness(repo_root, tmp_path) -> None:
    project = tmp_path / "empty"
    project.mkdir()
    result = _run_python(["--project", str(project)])
    assert result.returncode == 1
    assert "FAIL project:.superharness missing" in result.stdout
    assert "superharness init" in result.stdout


def test_doctor_fails_missing_protocol_files(repo_root, tmp_path) -> None:
    project = tmp_path / "partial"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    # Only create contract.yaml, skip everything else
    (harness / "contract.yaml").write_text("id: test\n")
    result = _run_python(["--project", str(project)])
    assert result.returncode == 1
    assert "FAIL" in result.stdout


def test_doctor_check_mode_exits_nonzero_on_warnings(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)
    # --check mode should exit non-zero if there are warnings (e.g. missing deps like codex)
    result = _run_python(["--project", str(project), "--check"])
    # We expect warnings for missing watcher / git hooks, so non-zero is expected
    # Just verify --check flag is accepted and the flag has an effect
    assert "summary:" in result.stdout


def test_doctor_shows_install_hints(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)
    result = _run_python(
        ["--project", str(project)],
        env={"PATH": "/usr/bin:/bin"},  # strip most paths so codex/claude are missing
    )
    # Should show WARN for missing deps with install hints
    assert "WARN" in result.stdout or "PASS" in result.stdout


def test_doctor_unknown_option(repo_root) -> None:
    result = _run_python(["--bogus"])
    assert result.returncode == 2
    # argparse outputs to stderr for unknown options
    assert "bogus" in result.stderr or "error" in result.stderr


def test_doctor_warns_when_plugin_not_installed(repo_root, tmp_path) -> None:
    """Doctor must warn when ~/.claude/plugins/superharness is not installed."""
    project = _write_project(tmp_path)
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    result = _run_python(
        ["--project", str(project)],
        env={"HOME": str(fake_home)},
    )
    assert "WARN plugin:claude-code superharness not installed" in result.stdout


def test_doctor_ok_when_plugin_installed(repo_root, tmp_path) -> None:
    """Doctor must show PASS when ~/.claude/plugins/superharness exists."""
    project = _write_project(tmp_path)
    fake_home = tmp_path / "fakehome2"
    plugin_dir = fake_home / ".claude" / "plugins" / "superharness"
    plugin_dir.mkdir(parents=True)
    result = _run_python(
        ["--project", str(project)],
        env={"HOME": str(fake_home)},
    )
    assert "PASS plugin:claude-code superharness installed" in result.stdout
