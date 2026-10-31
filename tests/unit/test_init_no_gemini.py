from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.helpers import REPO_ROOT


def _run_init(project: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [
        sys.executable,
        "-m",
        "superharness.commands.init_project",
        "NoGeminiTest",
        "Python",
        "greenfield",
        "--skip-hooks",
        *extra,
    ]
    return subprocess.run(
        cmd, cwd=str(project), text=True, capture_output=True, env=env, check=False
    )


def test_init_creates_gemini_md_by_default(tmp_path: Path) -> None:
    result = _run_init(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "GEMINI.md").is_file()


def test_init_no_gemini_skips_gemini_md(tmp_path: Path) -> None:
    result = _run_init(tmp_path, "--no-gemini")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "GEMINI.md").exists()
    assert (tmp_path / "CLAUDE.md").is_file()
    assert (tmp_path / "AGENTS.md").is_file()
    assert "Skipped: GEMINI.md (--no-gemini)" in result.stdout


def test_init_no_gemini_keeps_existing_gemini_md(tmp_path: Path) -> None:
    existing = tmp_path / "GEMINI.md"
    existing.write_text("user-owned\n", encoding="utf-8")
    result = _run_init(tmp_path, "--no-gemini")
    assert result.returncode == 0, result.stderr
    assert existing.read_text(encoding="utf-8") == "user-owned\n"


def test_dry_run_no_gemini_omits_gemini_md(tmp_path: Path) -> None:
    result = _run_init(tmp_path, "--no-gemini", "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "GEMINI.md" not in result.stdout
