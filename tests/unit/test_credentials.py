"""Tests for the shared machine-level credential store."""

from __future__ import annotations

import stat

import pytest


def test_credentials_path_honors_test_override(tmp_path, monkeypatch):
    from superharness.engine.credentials import credentials_path

    override = tmp_path / "credentials.env"
    monkeypatch.setenv("SUPERHARNESS_CREDENTIALS_FILE", str(override))
    assert credentials_path() == override


def test_read_credentials_file_parses_supported_lines(tmp_path):
    from superharness.engine.credentials import read_credentials_file

    path = tmp_path / "credentials.env"
    path.write_text(
        "# comment\nPLAIN=value\nDOUBLE=\"two words\"\n"
        "SINGLE='three words'\nMALFORMED\n\n",
        encoding="utf-8",
    )
    assert read_credentials_file(path) == {
        "PLAIN": "value",
        "DOUBLE": "two words",
        "SINGLE": "three words",
    }


def test_read_credentials_file_missing_is_empty(tmp_path):
    from superharness.engine.credentials import read_credentials_file

    assert read_credentials_file(tmp_path / "missing.env") == {}


def test_get_credential_preserves_file_first_precedence(tmp_path, monkeypatch):
    from superharness.engine.credentials import get_credential

    path = tmp_path / "credentials.env"
    path.write_text("EXAMPLE_KEY=file-value\n", encoding="utf-8")
    monkeypatch.setenv("SUPERHARNESS_CREDENTIALS_FILE", str(path))
    monkeypatch.setenv("EXAMPLE_KEY", "environment-value")
    assert get_credential("EXAMPLE_KEY") == "file-value"


def test_get_credential_falls_back_to_environment_and_default(tmp_path, monkeypatch):
    from superharness.engine.credentials import get_credential

    monkeypatch.setenv(
        "SUPERHARNESS_CREDENTIALS_FILE", str(tmp_path / "missing.env")
    )
    monkeypatch.setenv("ENV_ONLY", "environment-value")
    assert get_credential("ENV_ONLY") == "environment-value"
    assert get_credential("ABSENT", "fallback") == "fallback"


def test_write_credentials_file_preserves_unmanaged_content_and_sets_0600(tmp_path):
    from superharness.engine.credentials import write_credentials_file

    path = tmp_path / "nested" / "credentials.env"
    path.parent.mkdir()
    path.write_text("# retained\nUNMANAGED=keep\nMANAGED=old\n", encoding="utf-8")
    write_credentials_file({"MANAGED": "new", "ADDED": "value"}, path)
    assert path.read_text(encoding="utf-8") == (
        "# retained\nUNMANAGED=keep\nMANAGED=new\nADDED=value\n"
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_credentials_file_creates_parent_directory(tmp_path):
    from superharness.engine.credentials import write_credentials_file

    path = tmp_path / "new" / "credentials.env"
    write_credentials_file({"KEY": "value"}, path)
    assert path.read_text(encoding="utf-8") == "KEY=value\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_credentials_file_replaces_from_owner_only_temporary_file(
    tmp_path, monkeypatch
):
    from superharness.engine import credentials

    path = tmp_path / "credentials.env"
    observed_modes = []
    real_replace = credentials.os.replace

    def checked_replace(source, destination):
        observed_modes.append(stat.S_IMODE(credentials.Path(source).stat().st_mode))
        real_replace(source, destination)

    monkeypatch.setattr(credentials.os, "replace", checked_replace)
    credentials.write_credentials_file({"KEY": "value"}, path)

    assert observed_modes == [0o600]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_credentials_file_rejects_symlink_target(tmp_path):
    from superharness.engine.credentials import write_credentials_file

    destination = tmp_path / "destination.env"
    destination.write_text("UNCHANGED=true\n", encoding="utf-8")
    link = tmp_path / "credentials.env"
    link.symlink_to(destination)

    with pytest.raises(OSError, match="symbolic link"):
        write_credentials_file({"SECRET": "must-not-follow"}, link)

    assert destination.read_text(encoding="utf-8") == "UNCHANGED=true\n"


def test_relay_loaders_keep_existing_file_first_contract(tmp_path, monkeypatch):
    from superharness.engine.relay_client import (
        load_credentials,
        load_ntfy_credentials,
        load_telegram_credentials,
    )

    path = tmp_path / "credentials.env"
    path.write_text(
        "SUPERHARNESS_RELAY_SSH_HOST=relay-file\n"
        "SUPERHARNESS_RELAY_TOKEN=relay-token-file\n"
        "SUPERHARNESS_RELAY_DEST=telegram-file\n"
        "SUPERHARNESS_TELEGRAM_BOT_TOKEN=telegram-token-file\n"
        "SUPERHARNESS_TELEGRAM_CHAT_ID=chat-file\n"
        "SUPERHARNESS_NTFY_TOPIC=topic-file\n"
        "SUPERHARNESS_NTFY_SERVER=https://ntfy.example.test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUPERHARNESS_CREDENTIALS_FILE", str(path))
    monkeypatch.setenv("SUPERHARNESS_RELAY_TOKEN", "relay-token-env")
    assert load_credentials() == {
        "relay_token": "relay-token-file",
        "relay_ssh_host": "relay-file",
        "relay_dest": "telegram-file",
    }
    assert load_telegram_credentials() == {
        "bot_token": "telegram-token-file",
        "chat_id": "chat-file",
    }
    assert load_ntfy_credentials() == {
        "ntfy_topic": "topic-file",
        "ntfy_server": "https://ntfy.example.test",
    }
