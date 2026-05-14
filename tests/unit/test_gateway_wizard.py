"""Tests for gateway wizard section.

setup_gateway now routes through claw-relay:
  - relay credentials  → ~/.config/superharness/credentials.env (machine-level, 0600)
  - events checklist   → .superharness/profile.yaml (project-level, no secrets)
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def isolated_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect credentials file to a temp path so tests never touch the real one."""
    creds_file = tmp_path / "credentials.env"
    monkeypatch.setenv("SUPERHARNESS_CREDENTIALS_FILE", str(creds_file))
    # Also clear env vars that load_credentials falls back to
    monkeypatch.delenv("SUPERHARNESS_RELAY_TOKEN", raising=False)
    monkeypatch.delenv("SUPERHARNESS_RELAY_SSH_HOST", raising=False)
    monkeypatch.delenv("SUPERHARNESS_RELAY_DEST", raising=False)
    return creds_file


# ---------------------------------------------------------------------------
# relay_client: save_credentials / load_credentials
# ---------------------------------------------------------------------------

class TestSaveLoadCredentials:
    def test_credentials_written_to_machine_level_file(self, isolated_credentials: Path) -> None:
        from superharness.engine.relay_client import save_credentials, load_credentials

        save_credentials("user@10.255.86.217", "secret-token")
        creds = load_credentials()

        assert creds["relay_ssh_host"] == "user@10.255.86.217"
        assert creds["relay_token"] == "secret-token"
        assert creds["relay_dest"] == "telegram"

    def test_custom_dest_saved(self, isolated_credentials: Path) -> None:
        from superharness.engine.relay_client import save_credentials, load_credentials

        save_credentials("user@host", "tok", relay_dest="slack")
        assert load_credentials()["relay_dest"] == "slack"

    @pytest.mark.skipif(sys.platform == "win32", reason="chmod 0600 is a no-op on Windows")
    def test_credentials_file_chmod_600(self, isolated_credentials: Path) -> None:
        from superharness.engine.relay_client import save_credentials

        save_credentials("user@host", "tok")
        mode = isolated_credentials.stat().st_mode
        assert not (mode & stat.S_IRGRP), "group read must be cleared"
        assert not (mode & stat.S_IROTH), "other read must be cleared"

    def test_existing_unmanaged_keys_preserved(self, isolated_credentials: Path) -> None:
        from superharness.engine.relay_client import save_credentials

        isolated_credentials.write_text("ANTHROPIC_API_KEY=sk-existing\n")
        save_credentials("user@host", "tok")

        content = isolated_credentials.read_text()
        assert "ANTHROPIC_API_KEY=sk-existing" in content
        assert "SUPERHARNESS_RELAY_TOKEN=tok" in content

    def test_managed_keys_overwritten_on_second_call(self, isolated_credentials: Path) -> None:
        from superharness.engine.relay_client import save_credentials, load_credentials

        save_credentials("user@host-a", "tok-a")
        save_credentials("user@host-b", "tok-b")

        creds = load_credentials()
        assert creds["relay_ssh_host"] == "user@host-b"
        assert creds["relay_token"] == "tok-b"

    def test_is_configured_false_when_no_credentials(self, isolated_credentials: Path) -> None:
        from superharness.engine.relay_client import is_configured
        assert not is_configured()

    def test_is_configured_true_after_save(self, isolated_credentials: Path) -> None:
        from superharness.engine.relay_client import save_credentials, is_configured
        save_credentials("user@host", "tok")
        assert is_configured()


# ---------------------------------------------------------------------------
# setup_gateway: relay credentials saved to machine-level credentials file
# ---------------------------------------------------------------------------

class TestSetupGatewayCredentials:
    def test_relay_credentials_written_to_machine_level_file(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway
        from superharness.engine.relay_client import load_credentials

        setup_gateway(
            project_dir,
            relay_ssh_host="user@10.255.86.217",
            relay_token="my-relay-token",
            events=["plan_proposed"],
        )

        creds = load_credentials()
        assert creds["relay_ssh_host"] == "user@10.255.86.217"
        assert creds["relay_token"] == "my-relay-token"

    def test_credentials_not_written_to_project_profile(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(
            project_dir,
            relay_ssh_host="user@host",
            relay_token="secret",
            events=[],
        )

        profile_file = project_dir / ".superharness" / "profile.yaml"
        content = profile_file.read_text() if profile_file.exists() else ""
        assert "secret" not in content
        assert "user@host" not in content

    def test_credentials_not_written_to_watcher_env(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(
            project_dir,
            relay_ssh_host="user@host",
            relay_token="secret",
            events=[],
        )

        env_file = project_dir / ".superharness" / "watcher-env.yaml"
        content = env_file.read_text() if env_file.exists() else ""
        assert "secret" not in content

    @pytest.mark.skipif(sys.platform == "win32", reason="chmod 0600 is a no-op on Windows")
    def test_credentials_file_is_mode_600(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(project_dir, relay_ssh_host="u@h", relay_token="tok", events=[])

        mode = isolated_credentials.stat().st_mode
        assert not (mode & stat.S_IRGRP)
        assert not (mode & stat.S_IROTH)


# ---------------------------------------------------------------------------
# setup_gateway: events saved to profile.yaml
# ---------------------------------------------------------------------------

class TestSetupGatewayProfile:
    def test_events_written_to_profile(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        events = ["plan_proposed", "report_ready", "task_failed"]
        setup_gateway(
            project_dir,
            relay_ssh_host="u@h",
            relay_token="tok",
            events=events,
        )

        profile_file = project_dir / ".superharness" / "profile.yaml"
        assert profile_file.exists()
        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["gateway"]["events"] == events

    def test_backend_field_set_to_claw_relay(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(project_dir, relay_ssh_host="u@h", relay_token="tok", events=[])

        profile_file = project_dir / ".superharness" / "profile.yaml"
        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["gateway"]["backend"] == "claw-relay"

    def test_empty_events_list_written(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(project_dir, relay_ssh_host="u@h", relay_token="tok", events=[])

        profile_file = project_dir / ".superharness" / "profile.yaml"
        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["gateway"]["events"] == []

    def test_existing_profile_keys_preserved(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        profile_file = project_dir / ".superharness" / "profile.yaml"
        profile_file.write_text(yaml.dump({"autonomy": "supervised"}))

        setup_gateway(
            project_dir,
            relay_ssh_host="u@h",
            relay_token="tok",
            events=["plan_proposed"],
        )

        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["autonomy"] == "supervised"
        assert doc["gateway"]["events"] == ["plan_proposed"]

    def test_events_overwritten_on_second_call(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(
            project_dir, relay_ssh_host="u@h", relay_token="tok",
            events=["plan_proposed", "report_ready"],
        )
        setup_gateway(
            project_dir, relay_ssh_host="u@h", relay_token="tok",
            events=["task_closed"],
        )

        profile_file = project_dir / ".superharness" / "profile.yaml"
        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["gateway"]["events"] == ["task_closed"]

    def test_all_known_events_accepted(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway, ALL_GATEWAY_EVENTS

        setup_gateway(
            project_dir,
            relay_ssh_host="u@h",
            relay_token="tok",
            events=ALL_GATEWAY_EVENTS,
        )

        profile_file = project_dir / ".superharness" / "profile.yaml"
        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["gateway"]["events"] == ALL_GATEWAY_EVENTS
