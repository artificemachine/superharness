"""RED tests for write_field() in engine/profile.py."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml


def _write_field(project_dir: Path, field: str, value: str) -> None:
    from superharness.engine.profile import write_field
    write_field(project_dir, field, value)


def _read_profile(project_dir: Path) -> dict:
    profile_path = project_dir / ".superharness" / "profile.yaml"
    if not profile_path.exists():
        return {}
    return yaml.safe_load(profile_path.read_text()) or {}


# ---------------------------------------------------------------------------


def test_write_field_creates_profile_yaml_when_missing(tmp_path):
    """write_field creates .superharness/profile.yaml if it does not exist."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    _write_field(tmp_path, "autonomy", "full-auto")
    profile_path = sh / "profile.yaml"
    assert profile_path.exists(), "profile.yaml not created"
    doc = yaml.safe_load(profile_path.read_text())
    assert doc["autonomy"] == "full-auto"


def test_write_field_mutates_existing_key_in_place(tmp_path):
    """write_field updates an existing key without wiping the file."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    profile = sh / "profile.yaml"
    profile.write_text(yaml.dump({"autonomy": "supervised", "primary_agent": "claude-code"}))

    _write_field(tmp_path, "autonomy", "full-auto")

    doc = _read_profile(tmp_path)
    assert doc["autonomy"] == "full-auto"


def test_write_field_preserves_other_keys(tmp_path):
    """write_field must not destroy keys it is not updating."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    profile = sh / "profile.yaml"
    profile.write_text(yaml.dump({"autonomy": "supervised", "primary_agent": "codex-cli", "team_size": "small"}))

    _write_field(tmp_path, "autonomy", "full-auto")

    doc = _read_profile(tmp_path)
    assert doc["primary_agent"] == "codex-cli"
    assert doc["team_size"] == "small"
    assert doc["autonomy"] == "full-auto"


def test_write_field_idempotent_on_same_value(tmp_path):
    """Calling write_field twice with the same value leaves profile unchanged."""
    sh = tmp_path / ".superharness"
    sh.mkdir()

    _write_field(tmp_path, "autonomy", "supervised")
    _write_field(tmp_path, "autonomy", "supervised")

    doc = _read_profile(tmp_path)
    assert doc["autonomy"] == "supervised"


def test_write_field_creates_sh_dir_if_absent(tmp_path):
    """.superharness/ is created if the directory is missing."""
    # tmp_path has no .superharness/ yet
    _write_field(tmp_path, "team_size", "large")
    assert (tmp_path / ".superharness" / "profile.yaml").exists()
    doc = _read_profile(tmp_path)
    assert doc["team_size"] == "large"
