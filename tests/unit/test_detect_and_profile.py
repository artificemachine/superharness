from __future__ import annotations

import os
import subprocess
import sys

from tests.helpers import REPO_ROOT, run_cmd
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


# ── detect.py ────────────────────────────────────────────────────────────────

def _run_detect(repo_root, *args):
    return run_cmd([sys.executable, "-m", "superharness.engine.detect"] + list(args), cwd=repo_root)


def _run_init_py(cwd, args: list[str] | None = None):
    """Run init_project Python module."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.commands.init_project"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def test_detect_script_is_executable(repo_root) -> None:
    script = repo_root / "src/superharness/engine/detect.py"
    assert script.exists(), "src/superharness/engine/detect.py not found"


def test_detect_help(repo_root, tmp_path) -> None:
    result = _run_detect(repo_root, "--help")
    assert result.returncode == 0, result.stderr
    assert "Usage" in result.stdout or "detect" in result.stdout.lower()


def test_detect_outputs_valid_yaml_on_git_project(repo_root) -> None:
    result = _run_detect(repo_root, "--project", str(repo_root))
    assert result.returncode == 0, result.stderr
    assert "project_name:" in result.stdout
    assert "stack:" in result.stdout
    assert "status:" in result.stdout
    assert "team_size:" in result.stdout


def test_detect_finds_python_ruby_stack(repo_root) -> None:
    result = _run_detect(repo_root, "--project", str(repo_root))
    assert result.returncode == 0, result.stderr
    assert "Python" in result.stdout
    assert "Ruby" in result.stdout


def test_detect_non_git_project(repo_root, tmp_path) -> None:
    """detect.py must not crash on a directory with no .git/."""
    (tmp_path / "README.md").write_text("# Hello\n")
    result = _run_detect(repo_root, "--project", str(tmp_path))
    assert result.returncode == 0, f"detect.py crashed on non-git dir:\n{result.stderr}"
    assert "repo:" in result.stdout
    assert "team_size:" in result.stdout
    assert "status:" in result.stdout


def test_detect_non_git_returns_safe_defaults(repo_root, tmp_path) -> None:
    result = _run_detect(repo_root, "--project", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "repo: none" in result.stdout
    assert "team_size: solo" in result.stdout
    assert "greenfield" in result.stdout


def test_detect_project_name_from_package_json(repo_root, tmp_path) -> None:
    (tmp_path / "package.json").write_text('{"name": "my-node-app", "version": "1.0.0"}')
    result = _run_detect(repo_root, "--project", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert 'project_name: "my-node-app"' in result.stdout


def test_detect_project_name_from_pyproject_toml(repo_root, tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = \"my-python-app\"\nversion = \"0.1.0\"\n"
    )
    result = _run_detect(repo_root, "--project", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert 'project_name: "my-python-app"' in result.stdout


def test_detect_project_name_fallback_to_dirname(repo_root, tmp_path) -> None:
    project = tmp_path / "myproject"
    project.mkdir()
    result = _run_detect(repo_root, "--project", str(project))
    assert result.returncode == 0, result.stderr
    assert 'project_name: "myproject"' in result.stdout


def test_detect_output_flag(repo_root, tmp_path) -> None:
    out_file = tmp_path / "detected.yaml"
    result = _run_detect(repo_root, "--project", str(tmp_path), "--output", str(out_file))
    assert result.returncode == 0, result.stderr
    assert out_file.exists(), "--output file not created"
    content = out_file.read_text()
    assert "project_name:" in content


# ── init --from-profile ───────────────────────────────────────────────────────

def _write_profile(path, **overrides) -> None:
    defaults = {
        "project_name": "Test Project",
        "created": "2026-01-01",
        "autonomy": "supervised",
        "primary_agent": "codex-cli",
        "stack": "Python/Docker",
        "repo": "github",
        "ci": "github-actions",
        "team_size": "solo",
        "status": "active",
    }
    defaults.update(overrides)
    lines = "\n".join(f"{k}: {v!r}" if isinstance(v, str) else f"{k}: {v}"
                      for k, v in defaults.items())
    path.write_text(lines + "\n")


def test_init_from_profile_creates_files(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    profile = tmp_path / "profile.yaml"
    _write_profile(profile)

    result = _run_init_py(project, args=["--from-profile", str(profile)])
    assert result.returncode == 0, f"init --from-profile failed:\n{result.stdout}\n{result.stderr}"
    assert (project / ".superharness/contract.yaml").exists()
    assert (project / ".superharness/profile.yaml").exists()


def test_init_from_profile_uses_project_name(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    profile = tmp_path / "profile.yaml"
    _write_profile(profile, project_name="AwesomeApp")

    result = _run_init_py(project, args=["--from-profile", str(profile)])
    assert result.returncode == 0, result.stderr
    contract = (project / ".superharness/contract.yaml").read_text()
    assert "AwesomeApp" in contract


def test_init_from_profile_copies_profile_into_superharness(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    profile = tmp_path / "profile.yaml"
    _write_profile(profile)

    _run_init_py(project, args=["--from-profile", str(profile)])
    copied = project / ".superharness/profile.yaml"
    assert copied.exists(), "profile.yaml was not copied into .superharness/"


def test_init_from_profile_missing_file_errors(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    result = _run_init_py(project, args=["--from-profile", "/nonexistent/profile.yaml"])
    assert result.returncode != 0
    assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower()


def test_init_from_profile_source_outside_superharness_dir(repo_root, tmp_path) -> None:
    """Profile written to /tmp (not .superharness/) must work — dir doesn't exist yet."""
    project = tmp_path / "proj"
    project.mkdir()
    profile = tmp_path / "superharness-profile.yaml"  # outside project
    _write_profile(profile)

    result = _run_init_py(project, args=["--from-profile", str(profile)])
    assert result.returncode == 0, result.stderr
    assert (project / ".superharness").is_dir()


# ── init --detect ─────────────────────────────────────────────────────────────

def test_init_detect_creates_files(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname = "detect-test"\nversion = "0.1"\n')

    result = _run_init_py(project, args=["--detect"])
    assert result.returncode == 0, f"init --detect failed:\n{result.stdout}\n{result.stderr}"
    assert (project / ".superharness/contract.yaml").exists()


def test_init_detect_uses_detected_name(repo_root, tmp_path) -> None:
    project = tmp_path / "mydetectproject"
    project.mkdir()

    result = _run_init_py(project, args=["--detect"])
    assert result.returncode == 0, result.stderr
    contract = (project / ".superharness/contract.yaml").read_text()
    assert "mydetectproject" in contract
