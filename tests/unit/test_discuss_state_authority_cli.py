"""CLI regression tests for fail-closed discussion state authority."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


PYTHON = sys.executable


@pytest.mark.regression
@pytest.mark.parametrize(
    "args",
    [
        ["start", "--topic", "authority test", "--force"],
        ["pending", "--agent", "codex-cli"],
        [
            "submit",
            "--id",
            "discuss-fake",
            "--agent",
            "codex-cli",
            "--round",
            "1",
            "--verdict",
            "partial",
            "--position",
            "test",
        ],
        ["close", "--id", "discuss-fake"],
        ["approve", "--task", "fake"],
        ["status"],
    ],
    ids=["start", "pending", "submit", "close", "approve", "status"],
)
def test_state_authority_conflict_is_clean_cli_error(
    args: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    (project / ".superharness" / "handoffs").mkdir(parents=True)
    (project / ".superharness" / "discussions").mkdir()
    (project / ".superharness" / "state.sqlite3").touch()

    selected_state = tmp_path / "selected-state"
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(selected_state))

    result = subprocess.run(
        [
            PYTHON,
            "-m",
            "superharness.commands.discuss",
            *args,
            "--project",
            str(project),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Refusing to create or open another state database" in result.stderr
    assert "Traceback" not in result.stderr
    assert not selected_state.exists()
