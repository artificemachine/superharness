"""Tests for shux profile reset/lock/unlock (commands/profile_cmd.py).

TDD: written to expose a real NameError bug found by a 2026-07-21
portfolio-ready audit's ruff pass (F821 undefined-name) — `_reset_key()`
called `load_profile`/`save_profile` without importing them, the one
function in this file missing the local import every sibling function has.
Zero prior test coverage on this CLI surface let it ship undetected.
"""
from __future__ import annotations

import json

import pytest


@pytest.mark.regression
def test_profile_reset_removes_key(monkeypatch, tmp_path):
    """shux profile reset <key> deletes the key and re-saves the profile.

    Before the fix, this call raised NameError: name 'load_profile' is not
    defined, because `_reset_key()` never imported it.
    """
    import superharness.engine.behavioral as behavioral
    monkeypatch.setattr(behavioral, "USER_PROFILE_DIR", str(tmp_path))

    profile_file = tmp_path / "coding_style.json"
    profile_file.write_text(json.dumps({"tabs_vs_spaces": "spaces", "confidence": "high"}))

    from superharness.commands.profile_cmd import _reset_key
    _reset_key("tabs_vs_spaces")

    saved = json.loads(profile_file.read_text())
    assert "tabs_vs_spaces" not in saved
    assert saved["confidence"] == "high"


@pytest.mark.regression
def test_profile_reset_missing_key_no_crash(monkeypatch, tmp_path, capsys):
    """shux profile reset <key-not-present> prints a message, doesn't crash."""
    import superharness.engine.behavioral as behavioral
    monkeypatch.setattr(behavioral, "USER_PROFILE_DIR", str(tmp_path))

    profile_file = tmp_path / "coding_style.json"
    profile_file.write_text(json.dumps({"confidence": "high"}))

    from superharness.commands.profile_cmd import _reset_key
    _reset_key("nonexistent_key")

    assert "not found" in capsys.readouterr().out.lower()
