"""TDD coverage for conditional discovery of legacy state commands."""

from __future__ import annotations

from pathlib import Path
import re
from unittest.mock import patch

from click.testing import CliRunner

from superharness.cli import main


def _state_help(project: Path) -> str:
    result = CliRunner().invoke(
        main, ["state", "--help"], env={"SUPERHARNESS_PROJECT": str(project)}
    )
    assert result.exit_code == 0, result.output
    return result.output


def _has_command(output: str, command: str) -> bool:
    return re.search(rf"^  {re.escape(command)}\s{{2,}}", output, re.M) is not None


def test_clean_project_hides_legacy_state_commands(tmp_path: Path) -> None:
    output = _state_help(tmp_path)

    for command in ("archive", "export", "import", "migrate"):
        assert not _has_command(output, command)


def test_legacy_sqlite_reveals_migration_commands(tmp_path: Path) -> None:
    harness = tmp_path / ".superharness"
    harness.mkdir()
    (harness / "state.sqlite3").touch()

    output = _state_help(tmp_path)

    for command in ("archive", "export", "import", "migrate"):
        assert _has_command(output, command)


def test_legacy_yaml_reveals_yaml_commands(tmp_path: Path) -> None:
    harness = tmp_path / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text("tasks: []\n")

    output = _state_help(tmp_path)

    for command in ("archive", "export", "import", "migrate"):
        assert _has_command(output, command)


def test_help_all_always_documents_legacy_commands(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main, ["help", "--all"], env={"SUPERHARNESS_PROJECT": str(tmp_path)}
    )

    assert result.exit_code == 0, result.output
    for command in ("archive-yaml", "export-yaml", "import-yaml", "migrate-state"):
        assert command in result.output


def test_legacy_top_level_paths_remain_callable_when_hidden(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main, ["migrate-state", "--help"], env={"SUPERHARNESS_PROJECT": str(tmp_path)}
    )

    assert result.exit_code == 0, result.output


def test_superharness_project_controls_detection_root(tmp_path: Path, monkeypatch) -> None:
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    harness = other_dir / ".superharness"
    harness.mkdir()
    (harness / "state.sqlite3").touch()
    monkeypatch.chdir(tmp_path)

    output = _state_help(other_dir)

    assert "migrate" in output


def test_legacy_probe_oserror_degrades_to_hidden(tmp_path: Path) -> None:
    with patch("superharness.commands.help_catalog.Path.is_file", side_effect=OSError):
        output = _state_help(tmp_path)

    for command in ("archive", "export", "import", "migrate"):
        assert not _has_command(output, command)
