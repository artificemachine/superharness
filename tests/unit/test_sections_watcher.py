"""RED tests for the watcher section (ui/sections/watcher.py)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml


def _read_profile(project_dir: Path) -> dict:
    p = project_dir / ".superharness" / "profile.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def _run_watcher(project_dir: Path, platform_name: str = "Darwin", non_interactive: bool = True):
    from superharness.ui.sections.watcher import run
    with patch("platform.system", return_value=platform_name):
        run(project_dir, non_interactive=non_interactive)


# ---------------------------------------------------------------------------


def test_watcher_section_offers_launchd_on_darwin(tmp_path, capsys):
    """On Darwin the watcher section mentions launchd."""
    (tmp_path / ".superharness").mkdir()

    _run_watcher(tmp_path, platform_name="Darwin")

    out = capsys.readouterr().out
    assert "launchd" in out.lower()


def test_watcher_section_offers_systemd_on_linux(tmp_path, capsys):
    """On Linux the watcher section mentions systemd."""
    (tmp_path / ".superharness").mkdir()

    _run_watcher(tmp_path, platform_name="Linux")

    out = capsys.readouterr().out
    assert "systemd" in out.lower()


def test_watcher_section_writes_backend_to_profile(tmp_path):
    """watcher section writes watcher_backend to profile.yaml after running."""
    (tmp_path / ".superharness").mkdir()

    _run_watcher(tmp_path, platform_name="Darwin")

    doc = _read_profile(tmp_path)
    assert "watcher_backend" in doc
    assert doc["watcher_backend"] == "launchd"


def test_watcher_section_writes_systemd_backend_on_linux(tmp_path):
    """On Linux watcher_backend is recorded as systemd."""
    (tmp_path / ".superharness").mkdir()

    _run_watcher(tmp_path, platform_name="Linux")

    doc = _read_profile(tmp_path)
    assert doc.get("watcher_backend") == "systemd"


def test_watcher_section_noop_on_unsupported_platform(tmp_path, capsys):
    """On an unsupported platform the section prints a manual fallback hint."""
    (tmp_path / ".superharness").mkdir()

    _run_watcher(tmp_path, platform_name="Windows")

    out = capsys.readouterr().out
    # Should print a manual start hint rather than crashing
    assert "operator start" in out or "manual" in out.lower() or "shux" in out.lower()


def test_watcher_section_non_interactive_no_prompt(tmp_path, monkeypatch):
    """non_interactive=True never calls input()."""
    import builtins
    (tmp_path / ".superharness").mkdir()

    def _no_input(*a, **kw):
        raise AssertionError("input() called in non-interactive mode")

    monkeypatch.setattr(builtins, "input", _no_input)

    with patch("platform.system", return_value="Darwin"):
        from superharness.ui.sections.watcher import run
        run(tmp_path, non_interactive=True)
