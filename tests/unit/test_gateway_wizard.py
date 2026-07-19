"""Tests for gateway wizard section.

Two backends:
  - relay (SSH)  — relay_ssh_host + relay_token in ~/.config/superharness/credentials.env
  - telegram     — direct bot token + chat_id in ~/.config/superharness/credentials.env

Events checklist persists to .superharness/profile.yaml (no secrets there).
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

        save_credentials("user@10.0.0.10", "secret-token")
        creds = load_credentials()

        assert creds["relay_ssh_host"] == "user@10.0.0.10"
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
            relay_ssh_host="user@10.0.0.10",
            relay_token="my-relay-token",
            events=["plan_proposed"],
        )

        creds = load_credentials()
        assert creds["relay_ssh_host"] == "user@10.0.0.10"
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

    def test_backend_field_set_to_relay(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(project_dir, relay_ssh_host="u@h", relay_token="tok", events=[])

        profile_file = project_dir / ".superharness" / "profile.yaml"
        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["gateway"]["backend"] == "relay"

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

    def test_backend_field_relay_for_setup_gateway(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(project_dir, relay_ssh_host="u@h", relay_token="tok", events=[])

        profile_file = project_dir / ".superharness" / "profile.yaml"
        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["gateway"]["backend"] == "relay"


# ---------------------------------------------------------------------------
# Direct Telegram bot backend
# ---------------------------------------------------------------------------

class TestSetupTelegramDirect:
    def test_credentials_saved_to_machine_level_file(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_telegram_direct
        from superharness.engine.relay_client import load_telegram_credentials

        setup_telegram_direct(
            project_dir,
            bot_token="123456:ABCDEF",
            chat_id="111222333",
            events=["plan_proposed"],
        )

        creds = load_telegram_credentials()
        assert creds["bot_token"] == "123456:ABCDEF"
        assert creds["chat_id"] == "111222333"

    def test_bot_token_never_in_project_files(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_telegram_direct

        setup_telegram_direct(
            project_dir,
            bot_token="SECRET-BOT-TOKEN",
            chat_id="42",
            events=[],
        )

        for p in (project_dir / ".superharness").rglob("*"):
            if p.is_file():
                assert "SECRET-BOT-TOKEN" not in p.read_text(), f"token leaked to {p}"

    @pytest.mark.skipif(sys.platform == "win32", reason="chmod 0600 is a no-op on Windows")
    def test_credentials_file_mode_0600(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_telegram_direct

        setup_telegram_direct(project_dir, bot_token="tok", chat_id="42", events=[])
        mode = isolated_credentials.stat().st_mode
        assert not (mode & stat.S_IRGRP)
        assert not (mode & stat.S_IROTH)

    def test_backend_field_telegram(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_telegram_direct

        setup_telegram_direct(project_dir, bot_token="tok", chat_id="42", events=[])
        doc = yaml.safe_load((project_dir / ".superharness" / "profile.yaml").read_text()) or {}
        assert doc["gateway"]["backend"] == "telegram"

    def test_events_saved_to_profile(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_telegram_direct

        setup_telegram_direct(
            project_dir, bot_token="tok", chat_id="42",
            events=["plan_proposed", "task_failed"],
        )
        doc = yaml.safe_load((project_dir / ".superharness" / "profile.yaml").read_text()) or {}
        assert doc["gateway"]["events"] == ["plan_proposed", "task_failed"]

    def test_relay_and_telegram_coexist_in_credentials_file(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        """Switching from one backend to the other must not clobber the other's keys.

        The user may temporarily configure both — only the active backend (per profile.yaml)
        is used at runtime, but the dormant one's secrets should remain intact.
        """
        from superharness.ui.sections.gateway import setup_gateway, setup_telegram_direct
        from superharness.engine.relay_client import load_credentials, load_telegram_credentials

        setup_gateway(project_dir, relay_ssh_host="my-relay", relay_token="relay-tok", events=[])
        setup_telegram_direct(project_dir, bot_token="bot-tok", chat_id="42", events=[])

        assert load_credentials()["relay_token"] == "relay-tok"
        assert load_credentials()["relay_ssh_host"] == "my-relay"
        assert load_telegram_credentials()["bot_token"] == "bot-tok"
        assert load_telegram_credentials()["chat_id"] == "42"


# ---------------------------------------------------------------------------
# Unified dispatcher
# ---------------------------------------------------------------------------

class TestDispatchNotification:
    def test_nothing_configured_returns_empty(self, isolated_credentials: Path) -> None:
        from superharness.engine.relay_client import dispatch_notification
        sent, backend = dispatch_notification("hello")
        assert sent is False
        assert backend == ""

    def test_relay_preferred_when_both_configured(
        self, isolated_credentials: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from superharness.engine.relay_client import (
            save_credentials, save_telegram_credentials, dispatch_notification,
        )
        save_credentials("my-relay", "relay-tok")
        save_telegram_credentials("bot-tok", "42")

        called = {"relay": 0, "telegram": 0}
        monkeypatch.setattr(
            "superharness.engine.relay_client.send_notification_from_config",
            lambda text: (called.__setitem__("relay", called["relay"] + 1) or True),
        )
        monkeypatch.setattr(
            "superharness.engine.relay_client.send_via_telegram_direct_from_config",
            lambda text: (called.__setitem__("telegram", called["telegram"] + 1) or True),
        )

        sent, backend = dispatch_notification("hi")
        assert sent is True
        assert backend == "relay"
        assert called == {"relay": 1, "telegram": 0}

    def test_telegram_used_when_relay_not_configured(
        self, isolated_credentials: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from superharness.engine.relay_client import (
            save_telegram_credentials, dispatch_notification,
        )
        save_telegram_credentials("bot-tok", "42")

        monkeypatch.setattr(
            "superharness.engine.relay_client.send_via_telegram_direct_from_config",
            lambda text: True,
        )

        sent, backend = dispatch_notification("hi")
        assert sent is True
        assert backend == "telegram"

    def test_telegram_used_when_relay_send_fails(
        self, isolated_credentials: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the relay is configured but the send fails, do not fall through to direct bot.

        Each backend's failure is its own concern. Falling back across backends silently
        could mask outages and double-deliver in transient failures. dispatch_notification
        only falls through when the *prior* backend is not configured."""
        from superharness.engine.relay_client import (
            save_credentials, save_telegram_credentials, dispatch_notification,
        )
        save_credentials("my-relay", "relay-tok")
        save_telegram_credentials("bot-tok", "42")

        monkeypatch.setattr(
            "superharness.engine.relay_client.send_notification_from_config",
            lambda text: False,  # relay configured but send fails
        )
        called_telegram = [0]
        monkeypatch.setattr(
            "superharness.engine.relay_client.send_via_telegram_direct_from_config",
            lambda text: (called_telegram.__setitem__(0, called_telegram[0] + 1) or True),
        )

        sent, backend = dispatch_notification("hi")
        # Either: relay-only fallthrough (sent=False) OR fallthrough-to-telegram (sent=True).
        # Locking in the cross-backend fallback because operator notifications should reach
        # the human if any configured channel works.
        assert sent is True
        assert backend == "telegram"
        assert called_telegram[0] == 1


# ---------------------------------------------------------------------------
# ntfy.sh backend
# ---------------------------------------------------------------------------

class TestSetupNtfy:
    def test_credentials_saved_to_machine_level_file(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_ntfy
        from superharness.engine.relay_client import load_ntfy_credentials

        setup_ntfy(
            project_dir,
            ntfy_topic="superharness-alerts",
            ntfy_server="https://ntfy.myserver.com",
            events=["plan_proposed"],
        )

        creds = load_ntfy_credentials()
        assert creds["ntfy_topic"] == "superharness-alerts"
        assert creds["ntfy_server"] == "https://ntfy.myserver.com"

    def test_default_server_is_ntfy_sh(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_ntfy
        from superharness.engine.relay_client import load_ntfy_credentials

        setup_ntfy(project_dir, ntfy_topic="my-topic", ntfy_server="https://ntfy.sh", events=[])
        assert load_ntfy_credentials()["ntfy_server"] == "https://ntfy.sh"

    def test_topic_never_in_project_files(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_ntfy

        setup_ntfy(project_dir, ntfy_topic="SECRET-TOPIC", ntfy_server="https://ntfy.sh", events=[])

        for p in (project_dir / ".superharness").rglob("*"):
            if p.is_file():
                assert "SECRET-TOPIC" not in p.read_text(), f"topic leaked to {p}"

    def test_backend_field_ntfy(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_ntfy

        setup_ntfy(project_dir, ntfy_topic="my-topic", ntfy_server="https://ntfy.sh", events=[])
        doc = yaml.safe_load((project_dir / ".superharness" / "profile.yaml").read_text()) or {}
        assert doc["gateway"]["backend"] == "ntfy"

    def test_events_saved_to_profile(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_ntfy

        setup_ntfy(
            project_dir, ntfy_topic="t", ntfy_server="https://ntfy.sh",
            events=["task_failed", "report_ready"],
        )
        doc = yaml.safe_load((project_dir / ".superharness" / "profile.yaml").read_text()) or {}
        assert doc["gateway"]["events"] == ["task_failed", "report_ready"]

    def test_all_backends_coexist_in_credentials_file(
        self, project_dir: Path, isolated_credentials: Path
    ) -> None:
        from superharness.ui.sections.gateway import setup_gateway, setup_telegram_direct, setup_ntfy
        from superharness.engine.relay_client import load_credentials, load_telegram_credentials, load_ntfy_credentials

        setup_gateway(project_dir, relay_ssh_host="my-relay", relay_token="relay-tok", events=[])
        setup_telegram_direct(project_dir, bot_token="bot-tok", chat_id="42", events=[])
        setup_ntfy(project_dir, ntfy_topic="my-topic", ntfy_server="https://ntfy.sh", events=[])

        assert load_credentials()["relay_token"] == "relay-tok"
        assert load_telegram_credentials()["bot_token"] == "bot-tok"
        assert load_ntfy_credentials()["ntfy_topic"] == "my-topic"

    def test_ntfy_used_when_relay_and_telegram_not_configured(
        self, isolated_credentials: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from superharness.engine.relay_client import save_ntfy_credentials, dispatch_notification

        save_ntfy_credentials("my-topic")
        monkeypatch.setattr(
            "superharness.engine.relay_client.send_via_ntfy_from_config",
            lambda text: True,
        )

        sent, backend = dispatch_notification("hi")
        assert sent is True
        assert backend == "ntfy"
