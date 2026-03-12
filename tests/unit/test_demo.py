from __future__ import annotations

import os
import stat

import pytest

from tests.helpers import run_bash


def test_demo_script_is_executable(repo_root) -> None:
    script = repo_root / "scripts/demo.sh"
    assert script.exists(), "scripts/demo.sh not found"
    mode = script.stat().st_mode
    assert mode & stat.S_IXUSR, "scripts/demo.sh is not executable"


def test_demo_help(repo_root, tmp_path) -> None:
    result = run_bash(repo_root / "scripts/demo.sh", cwd=tmp_path, args=["--help"])
    assert result.returncode == 0, result.stderr
    assert "lifecycle" in result.stdout


def test_demo_runs_to_completion(repo_root, tmp_path) -> None:
    result = run_bash(repo_root / "scripts/demo.sh", cwd=tmp_path)
    assert result.returncode == 0, f"demo failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_demo_all_five_steps_present(repo_root, tmp_path) -> None:
    result = run_bash(repo_root / "scripts/demo.sh", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    for step in ("1 / 5", "2 / 5", "3 / 5", "4 / 5", "5 / 5"):
        assert step in result.stdout, f"Expected step marker '{step}' in demo output"


def test_demo_output_contains_summary(repo_root, tmp_path) -> None:
    result = run_bash(repo_root / "scripts/demo.sh", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Demo complete" in result.stdout
    assert "hygiene" in result.stdout.lower()


def test_demo_cleans_up_temp_dir(repo_root, tmp_path) -> None:
    """Temp dir created by demo should be removed on exit (no --keep flag)."""
    result = run_bash(repo_root / "scripts/demo.sh", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    # Extract temp path from output header
    for line in result.stdout.splitlines():
        if line.startswith("Temp project:"):
            temp_dir = line.split("Temp project:", 1)[1].strip()
            assert not os.path.exists(temp_dir), f"Temp dir was not cleaned up: {temp_dir}"
            break
    else:
        pytest.fail("Could not find 'Temp project:' line in demo output")


def test_demo_keep_flag_preserves_dir(repo_root, tmp_path) -> None:
    result = run_bash(repo_root / "scripts/demo.sh", cwd=tmp_path, args=["--keep"])
    assert result.returncode == 0, result.stderr
    assert "Demo directory kept at:" in result.stdout
    # Extract kept path and verify it exists
    for line in result.stdout.splitlines():
        if line.strip().startswith("Demo directory kept at:"):
            kept_dir = line.split("Demo directory kept at:", 1)[1].strip()
            assert os.path.isdir(kept_dir), f"--keep dir not found: {kept_dir}"
            # cleanup manually so tmp_path teardown is clean
            import shutil
            shutil.rmtree(kept_dir, ignore_errors=True)
            break
    else:
        pytest.fail("Could not find 'Demo directory kept at:' line in output")
