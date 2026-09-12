from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.helpers import REPO_ROOT, run_bash, shell_guard_list
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


# Entrypoints that should respond to --help with exit 0.
# Bash-shim scripts (delegate.sh, discuss.sh, monitor-ui.sh) have been deleted;
# their functionality is now in Python modules.
HELP_ENTRYPOINTS = [
    "superharness",
    "src/superharness/scripts/delegate-task.sh",
]


def _run_py_module_help(module: str, cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", module, "--help"],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )




def test_discuss_help_lists_core_subcommands(repo_root: Path) -> None:
    # discuss is now a Python module (scripts/discuss.sh was a shim, now deleted)
    result = _run_py_module_help("superharness.commands.discuss", repo_root)
    assert result.returncode == 0, f"discuss --help failed: {result.stderr}"
    assert "start" in result.stdout
    assert "rounds" in result.stdout
    assert "consensus" in result.stdout
    assert "list" in result.stdout
