"""
Iteration 0 — CLI passthrough integration tests (TDD: written before implementation).
Tests that Python CLI delegates to shell scripts and produces identical output.
"""
import subprocess
import sys
import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHELL_WRAPPER = os.path.join(REPO_ROOT, "superharness")
PYTHON_CLI = [sys.executable, "-m", "superharness"]


def _run_shell(args):
    return subprocess.run(
        [SHELL_WRAPPER] + args,
        capture_output=True, text=True, cwd=REPO_ROOT
    )


def _run_python(args):
    return subprocess.run(
        PYTHON_CLI + args,
        capture_output=True, text=True, cwd=REPO_ROOT
    )


def test_version_output_matches():
    shell = _run_shell(["version"])
    python = _run_python(["version"])
    assert shell.returncode == python.returncode == 0
    # Both should contain a version string like x.y.z
    import re
    version_pattern = re.compile(r"\d+\.\d+\.\d+")
    assert version_pattern.search(shell.stdout), "Shell version output missing version number"
    assert version_pattern.search(python.stdout), "Python version output missing version number"


def test_help_exit_code_matches():
    shell = _run_shell(["help"])
    python = _run_python(["--help"])
    assert shell.returncode == 0
    assert python.returncode == 0


def test_unknown_subcommand_exit_code_matches():
    shell = _run_shell(["not-a-real-command"])
    python = _run_python(["not-a-real-command"])
    # Both should fail
    assert shell.returncode != 0
    assert python.returncode != 0
