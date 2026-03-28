"""Tests for superharness.engine.env_snapshot."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a minimal project with .superharness dir."""
    harness = tmp_path / ".superharness"
    harness.mkdir()
    return tmp_path


# ---- snapshot ----

def test_snapshot_creates_yaml(project: Path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
    monkeypatch.setenv("PATH", "/usr/bin:/usr/local/bin")

    from superharness.engine.env_snapshot import snapshot
    env_file = snapshot(project)

    assert env_file.exists()
    doc = yaml.safe_load(env_file.read_text())
    assert doc["env"]["ANTHROPIC_API_KEY"] == "sk-ant-test-123"
    assert doc["env"]["PATH"] == "/usr/bin:/usr/local/bin"
    assert "captured_at" in doc


def test_snapshot_chmod_600(project: Path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    from superharness.engine.env_snapshot import snapshot
    env_file = snapshot(project)

    mode = env_file.stat().st_mode
    assert not (mode & stat.S_IRGRP), "group-readable"
    assert not (mode & stat.S_IROTH), "world-readable"
    assert mode & stat.S_IRUSR, "owner should be able to read"


def test_snapshot_only_captures_present_keys(project: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")

    from superharness.engine.env_snapshot import snapshot
    env_file = snapshot(project)

    doc = yaml.safe_load(env_file.read_text())
    assert "ANTHROPIC_API_KEY" not in doc["env"]
    assert doc["env"]["PATH"] == "/usr/bin"


def test_snapshot_adds_gitignore(project: Path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    gitignore = project / ".gitignore"
    gitignore.write_text("*.pyc\n")

    from superharness.engine.env_snapshot import snapshot
    snapshot(project)

    content = gitignore.read_text()
    assert ".superharness/watcher-env.yaml" in content


def test_snapshot_gitignore_idempotent(project: Path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    gitignore = project / ".gitignore"
    gitignore.write_text(".superharness/watcher-env.yaml\n")

    from superharness.engine.env_snapshot import snapshot
    snapshot(project)

    content = gitignore.read_text()
    assert content.count("watcher-env.yaml") == 1


def test_snapshot_raises_on_missing_harness(tmp_path: Path, monkeypatch):
    from superharness.engine.env_snapshot import snapshot
    with pytest.raises(FileNotFoundError):
        snapshot(tmp_path)


# ---- load ----

def test_load_returns_env(project: Path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-load-test")

    from superharness.engine.env_snapshot import snapshot, load
    snapshot(project)
    env = load(project)

    assert env["ANTHROPIC_API_KEY"] == "sk-load-test"


def test_load_returns_empty_if_missing(project: Path):
    from superharness.engine.env_snapshot import load
    assert load(project) == {}


# ---- merge_env ----

def test_merge_does_not_override_existing(project: Path, monkeypatch):
    """Captured values fill gaps but don't override real env vars."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "real-key")

    from superharness.engine.env_snapshot import snapshot, merge_env
    # Snapshot captures "real-key"
    snapshot(project)
    # Now change the real env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "newer-key")

    merged = merge_env(project)
    assert merged["ANTHROPIC_API_KEY"] == "newer-key"  # real env wins


def test_merge_fills_missing_keys(project: Path, monkeypatch):
    """Captured values fill in keys missing from current env."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "captured-key")

    from superharness.engine.env_snapshot import snapshot, merge_env
    snapshot(project)
    monkeypatch.delenv("ANTHROPIC_API_KEY")

    merged = merge_env(project)
    assert merged["ANTHROPIC_API_KEY"] == "captured-key"


# ---- check (doctor) ----

def test_check_warns_on_missing(project: Path):
    from superharness.engine.env_snapshot import check
    status, msgs = check(project)
    assert status == "WARN"
    assert any("not found" in m for m in msgs)


def test_check_warns_on_no_api_keys(project: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")

    from superharness.engine.env_snapshot import snapshot, check
    snapshot(project)
    status, msgs = check(project)
    assert status == "WARN"
    assert any("no API keys" in m for m in msgs)


def test_check_passes_with_keys(project: Path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-good")
    monkeypatch.setenv("PATH", "/usr/bin")

    from superharness.engine.env_snapshot import snapshot, check
    snapshot(project)
    status, msgs = check(project)
    assert status == "PASS"
    assert any("ok" in m for m in msgs)
