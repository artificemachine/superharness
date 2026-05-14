from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests.helpers import REPO_ROOT


def _run_demo_py(cwd, args: list[str] | None = None):
    """Run demo Python module."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.commands.demo"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def test_demo_module_exists(repo_root) -> None:
    module = repo_root / "src/superharness/commands/demo.py"
    assert module.exists(), "src/superharness/commands/demo.py not found"


def test_demo_help(repo_root, tmp_path) -> None:
    result = _run_demo_py(tmp_path, args=["--help"])
    assert result.returncode == 0, result.stderr
    assert "lifecycle" in result.stdout


def test_demo_runs_to_completion(repo_root, tmp_path) -> None:
    result = _run_demo_py(tmp_path)
    assert result.returncode == 0, f"demo failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_demo_all_steps_present(repo_root, tmp_path) -> None:
    result = _run_demo_py(tmp_path)
    assert result.returncode == 0, result.stderr
    # Demo has 17 steps — verify first, middle, and last markers are present.
    for step in ("1 / 17", "9 / 17", "17 / 17"):
        assert step in result.stdout, f"Expected step marker '{step}' in demo output"


def test_demo_output_contains_summary(repo_root, tmp_path) -> None:
    result = _run_demo_py(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Demo complete" in result.stdout
    assert "hygiene" in result.stdout.lower()


def test_demo_cleans_up_temp_dir(repo_root, tmp_path) -> None:
    """Temp dir created by demo should be removed on exit (no --keep flag)."""
    result = _run_demo_py(tmp_path)
    assert result.returncode == 0, result.stderr
    # Extract temp path from output header
    for line in result.stdout.splitlines():
        if "Temp project:" in line:
            temp_dir = line.split("Temp project:", 1)[1].strip().rstrip()
            assert not os.path.exists(temp_dir), f"Temp dir was not cleaned up: {temp_dir}"
            break
    else:
        pytest.fail("Could not find 'Temp project:' line in demo output")


def test_demo_keep_flag_preserves_dir(repo_root, tmp_path) -> None:
    result = _run_demo_py(tmp_path, args=["--keep"])
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
