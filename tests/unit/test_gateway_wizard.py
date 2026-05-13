"""Tests for I7: Gateway wizard section.

Acceptance criteria:
  - setup_gateway saves token and allowlist to watcher-env.yaml
  - setup_gateway saves events checklist to profile.yaml
"""
from __future__ import annotations

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


# ---------------------------------------------------------------------------
# setup_gateway: token + allowlist saved to watcher-env.yaml
# ---------------------------------------------------------------------------

class TestSetupGatewayEnv:
    def test_token_written_to_watcher_env(self, project_dir: Path) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(
            project_dir,
            token="1234567890:ABCDefgh",
            allowed_senders=["111222333"],
            events=["plan_proposed"],
        )

        env_file = project_dir / ".superharness" / "watcher-env.yaml"
        assert env_file.exists(), "watcher-env.yaml should be created"
        doc = yaml.safe_load(env_file.read_text()) or {}
        assert doc["env"]["SUPERHARNESS_TELEGRAM_BOT_TOKEN"] == "1234567890:ABCDefgh"

    def test_allowlist_written_as_csv(self, project_dir: Path) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(
            project_dir,
            token="tok",
            allowed_senders=["111", "222", "333"],
            events=[],
        )

        env_file = project_dir / ".superharness" / "watcher-env.yaml"
        doc = yaml.safe_load(env_file.read_text()) or {}
        assert doc["env"]["SUPERHARNESS_TELEGRAM_ALLOWED_SENDERS"] == "111,222,333"

    @pytest.mark.skipif(sys.platform == "win32", reason="chmod 600 is a no-op on Windows")
    def test_watcher_env_chmod_600(self, project_dir: Path) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(
            project_dir,
            token="tok",
            allowed_senders=["42"],
            events=[],
        )

        env_file = project_dir / ".superharness" / "watcher-env.yaml"
        mode = env_file.stat().st_mode
        # Group and other must not have read permission
        assert not (mode & stat.S_IRGRP), "group read should be cleared"
        assert not (mode & stat.S_IROTH), "other read should be cleared"

    def test_existing_env_vars_preserved(self, project_dir: Path) -> None:
        """setup_gateway merges into existing watcher-env.yaml, not clobbers."""
        from superharness.ui.sections.gateway import setup_gateway

        env_file = project_dir / ".superharness" / "watcher-env.yaml"
        env_file.write_text(yaml.dump({"env": {"ANTHROPIC_API_KEY": "sk-existing"}}))

        setup_gateway(
            project_dir,
            token="tok",
            allowed_senders=["42"],
            events=[],
        )

        doc = yaml.safe_load(env_file.read_text()) or {}
        assert doc["env"]["ANTHROPIC_API_KEY"] == "sk-existing"
        assert doc["env"]["SUPERHARNESS_TELEGRAM_BOT_TOKEN"] == "tok"

    def test_empty_allowlist_written(self, project_dir: Path) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(project_dir, token="tok", allowed_senders=[], events=[])

        env_file = project_dir / ".superharness" / "watcher-env.yaml"
        doc = yaml.safe_load(env_file.read_text()) or {}
        assert doc["env"]["SUPERHARNESS_TELEGRAM_ALLOWED_SENDERS"] == ""


# ---------------------------------------------------------------------------
# setup_gateway: events saved to profile.yaml
# ---------------------------------------------------------------------------

class TestSetupGatewayProfile:
    def test_events_written_to_profile(self, project_dir: Path) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        events = ["plan_proposed", "report_ready", "task_failed"]
        setup_gateway(
            project_dir,
            token="tok",
            allowed_senders=["42"],
            events=events,
        )

        profile_file = project_dir / ".superharness" / "profile.yaml"
        assert profile_file.exists(), "profile.yaml should be created"
        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["gateway"]["events"] == events

    def test_empty_events_list_written(self, project_dir: Path) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(project_dir, token="tok", allowed_senders=["42"], events=[])

        profile_file = project_dir / ".superharness" / "profile.yaml"
        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["gateway"]["events"] == []

    def test_existing_profile_keys_preserved(self, project_dir: Path) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        profile_file = project_dir / ".superharness" / "profile.yaml"
        profile_file.write_text(yaml.dump({"autonomy": "supervised"}))

        setup_gateway(
            project_dir,
            token="tok",
            allowed_senders=["42"],
            events=["plan_proposed"],
        )

        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["autonomy"] == "supervised"
        assert doc["gateway"]["events"] == ["plan_proposed"]

    def test_events_overwritten_on_second_call(self, project_dir: Path) -> None:
        from superharness.ui.sections.gateway import setup_gateway

        setup_gateway(
            project_dir, token="tok", allowed_senders=["1"],
            events=["plan_proposed", "report_ready"],
        )
        setup_gateway(
            project_dir, token="tok", allowed_senders=["1"],
            events=["task_closed"],
        )

        profile_file = project_dir / ".superharness" / "profile.yaml"
        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["gateway"]["events"] == ["task_closed"]

    def test_all_known_events_accepted(self, project_dir: Path) -> None:
        from superharness.ui.sections.gateway import setup_gateway, ALL_GATEWAY_EVENTS

        setup_gateway(
            project_dir,
            token="tok",
            allowed_senders=["42"],
            events=ALL_GATEWAY_EVENTS,
        )

        profile_file = project_dir / ".superharness" / "profile.yaml"
        doc = yaml.safe_load(profile_file.read_text()) or {}
        assert doc["gateway"]["events"] == ALL_GATEWAY_EVENTS
