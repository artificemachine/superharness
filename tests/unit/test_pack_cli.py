"""Tests for superharness pack CLI command."""
from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path) -> Path:
    """Create a minimal fake project with .superharness/."""
    sh = tmp_path / ".superharness"
    sh.mkdir(parents=True)
    contract = {"project_path": "/Users/test/myapp", "tasks": []}
    (sh / "contract.yaml").write_text(yaml.dump(contract))
    (sh / "ledger.md").write_text("# Ledger\n")
    return tmp_path


def _run_pack(argv: list[str]) -> tuple[int, str, str]:
    """Invoke pack.main() and capture stdout/stderr + exit code."""
    import io as _io
    from superharness.commands.pack import main

    stdout_cap = _io.StringIO()
    stderr_cap = _io.StringIO()
    exit_code = 0

    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = stdout_cap
    sys.stderr = stderr_cap
    try:
        main(argv)
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 0
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    return exit_code, stdout_cap.getvalue(), stderr_cap.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_pack_export_command_creates_file(tmp_path):
    project = _make_project(tmp_path / "myproject")

    code, out, err = _run_pack(["export", "--project", str(project), "--output", str(tmp_path / "out.tar.gz")])

    assert code == 0, f"stderr: {err}"
    assert (tmp_path / "out.tar.gz").exists()
    assert "Exported pack" in out


def test_pack_export_command_with_output_flag(tmp_path):
    project = _make_project(tmp_path / "myproject")
    named_output = tmp_path / "custom-name.superharness.pack.tar.gz"

    code, out, err = _run_pack(["export", "--project", str(project), "--output", str(named_output)])

    assert code == 0, f"stderr: {err}"
    assert named_output.exists()


def test_pack_import_command_extracts_files(tmp_path):
    project = _make_project(tmp_path / "src")
    pack_file = tmp_path / "out.tar.gz"
    _run_pack(["export", "--project", str(project), "--output", str(pack_file)])

    dest = tmp_path / "dest"
    dest.mkdir()

    code, out, err = _run_pack(["import", str(pack_file), "--project", str(dest)])

    assert code == 0, f"stderr: {err}"
    assert (dest / ".superharness" / "contract.yaml").exists()
    assert "Imported" in out


def test_pack_import_collision_skip(tmp_path):
    project = _make_project(tmp_path / "src")
    pack_file = tmp_path / "out.tar.gz"
    _run_pack(["export", "--project", str(project), "--output", str(pack_file)])

    dest = tmp_path / "dest"
    sh = dest / ".superharness"
    sh.mkdir(parents=True)
    original = b"original content\n"
    (sh / "contract.yaml").write_bytes(original)

    code, out, err = _run_pack(["import", str(pack_file), "--project", str(dest), "--collision", "skip"])

    assert code == 0, f"stderr: {err}"
    assert (sh / "contract.yaml").read_bytes() == original


def test_pack_import_collision_overwrite(tmp_path):
    project = _make_project(tmp_path / "src")
    pack_file = tmp_path / "out.tar.gz"
    _run_pack(["export", "--project", str(project), "--output", str(pack_file)])

    dest = tmp_path / "dest"
    sh = dest / ".superharness"
    sh.mkdir(parents=True)
    (sh / "contract.yaml").write_bytes(b"original content\n")

    code, out, err = _run_pack(["import", str(pack_file), "--project", str(dest), "--collision", "overwrite"])

    assert code == 0, f"stderr: {err}"
    content = (sh / "contract.yaml").read_text()
    assert "original content" not in content


def test_pack_help(tmp_path):
    code, out, err = _run_pack(["--help"])
    # argparse exits 0 for --help
    assert code == 0


def test_pack_no_subcommand_exits_nonzero(tmp_path):
    code, out, err = _run_pack([])
    assert code != 0


def test_pack_export_missing_project_exits_nonzero(tmp_path):
    no_sh = tmp_path / "empty"
    no_sh.mkdir()

    code, out, err = _run_pack(["export", "--project", str(no_sh)])

    assert code != 0
    assert len(err) > 0
