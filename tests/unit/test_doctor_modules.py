"""Tests for doctor module health section."""
from __future__ import annotations

import sys
from pathlib import Path


from tests.helpers import REPO_ROOT, seed_sqlite_from_yaml


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
    """Create minimal valid project structure."""
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()
    (harness / "contract.yaml").write_text("id: test\ntasks: []\n")
    (harness / "ledger.md").write_text("# Ledger\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    seed_sqlite_from_yaml(project)
    return project


class TestDoctorModules:
    """Tests for doctor module health section."""

    def test_doctor_shows_enabled_modules(self, tmp_path) -> None:
        """Doctor lists enabled modules with status."""
        project = _write_project(tmp_path)
        modules_dir = project / ".superharness" / "modules"
        modules_dir.mkdir(parents=True, exist_ok=True)

        # Enable 3 modules: obsidian, security, ntfy
        (modules_dir / "obsidian.yaml").write_text(
            "name: obsidian\nenabled: true\ndetect:\n  env: OBSIDIAN_VAULT\n"
        )
        (modules_dir / "security.yaml").write_text(
            "name: security\nenabled: true\n"
        )
        (modules_dir / "ntfy.yaml").write_text(
            "name: ntfy\nenabled: true\ndetect:\n  env: NTFY_TOPIC\n"
        )

        result = _run_python(["--project", str(project)])
        assert result.returncode == 0
        assert "PASS modules: 3 enabled (ntfy, obsidian, security)" in result.stdout

    def test_doctor_shows_missing_dependencies(self, tmp_path) -> None:
        """Module enabled but dependency missing → WARN."""
        project = _write_project(tmp_path)
        modules_dir = project / ".superharness" / "modules"
        modules_dir.mkdir(parents=True, exist_ok=True)

        # Enable telegram module with TELEGRAM_BOT_TOKEN dependency
        (modules_dir / "telegram.yaml").write_text(
            "name: telegram\nenabled: true\ndetect:\n  env: TELEGRAM_BOT_TOKEN\n"
        )

        # Run doctor with TELEGRAM_BOT_TOKEN unset
        result = _run_python(
            ["--project", str(project)],
            env={"TELEGRAM_BOT_TOKEN": None}
        )
        assert "WARN module:telegram — TELEGRAM_BOT_TOKEN not set" in result.stdout

    def test_doctor_suggests_enhance(self, tmp_path) -> None:
        """No modules enabled → INFO with 'shux enhance' suggestion."""
        project = _write_project(tmp_path)
        # Do NOT create modules directory — no modules enabled

        result = _run_python(["--project", str(project)])
        assert result.returncode == 0
        assert "INFO modules:" in result.stdout
        assert "shux enhance" in result.stdout
