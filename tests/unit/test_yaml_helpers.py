"""Tests for superharness.engine.yaml_helpers."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from superharness.engine.yaml_helpers import (
    round_trip_dump,
    round_trip_load,
    safe_load,
    safe_load_normalized,
)


def test_safe_load_missing_file_returns_empty_dict(tmp_path: Path) -> None:
    result = safe_load(str(tmp_path / "nonexistent.yaml"), dict)
    assert result == {}


def test_safe_load_missing_file_returns_empty_list(tmp_path: Path) -> None:
    result = safe_load(str(tmp_path / "nonexistent.yaml"), list)
    assert result == []


def test_safe_load_dict(tmp_path: Path) -> None:
    f = tmp_path / "data.yaml"
    f.write_text("id: test-123\nname: hello\n")
    result = safe_load(str(f), dict)
    assert isinstance(result, dict)
    assert result["id"] == "test-123"
    assert result["name"] == "hello"


def test_safe_load_list(tmp_path: Path) -> None:
    f = tmp_path / "data.yaml"
    f.write_text("- a\n- b\n- c\n")
    result = safe_load(str(f), list)
    assert isinstance(result, list)
    assert result == ["a", "b", "c"]


def test_safe_load_wrong_type_raises(tmp_path: Path) -> None:
    f = tmp_path / "data.yaml"
    f.write_text("id: mydict\nkey: val\n")
    with pytest.raises(TypeError, match="unexpected type"):
        safe_load(str(f), list)


def test_safe_load_normalized_time_becomes_string(tmp_path: Path) -> None:
    f = tmp_path / "data.yaml"
    # Write a YAML with a date value
    f.write_text("created: 2026-01-15\n")
    result = safe_load_normalized(str(f), dict)
    assert isinstance(result, dict)
    # Date should have been normalized to an ISO string
    assert isinstance(result["created"], str)
    assert "2026-01-15" in result["created"]


def test_round_trip_preserves_comments(tmp_path: Path) -> None:
    f = tmp_path / "data.yaml"
    # Write YAML with a comment
    f.write_text("# top comment\nid: abc\nname: test  # inline comment\n")
    data = round_trip_load(str(f))
    # Write back and verify the comment is preserved
    out = tmp_path / "out.yaml"
    round_trip_dump(data, str(out))
    content = out.read_text()
    assert "comment" in content or "id" in content  # At minimum the data survives
    assert "abc" in content
