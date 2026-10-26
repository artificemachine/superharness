"""Tests for `shux models` (commands/models.py)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from superharness.commands.models import main as models_main


def _bindings(verified: date) -> str:
    return f"""schema: 2
providers:
  test-provider:
    verified: {verified.isoformat()}
harnesses:
  codex-cli:
    default_provider: test-provider
    bindings:
      test-provider:
        bulk:
          id: model-bulk
        default:
          id: model-default
        escalate-1:
          id: model-max
"""


@pytest.fixture
def config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "superharness-config"
    directory.mkdir()
    monkeypatch.setenv("SUPERHARNESS_CONFIG_DIR", str(directory))
    return directory


def test_check_missing_file_exits_2(config_dir: Path) -> None:
    """No bindings file: the path is named, adapter defaults are announced, exit 2."""
    result = CliRunner().invoke(models_main, ["check"])

    assert result.exit_code == 2
    assert str(config_dir / "model-bindings.yaml") in result.output
    assert "adapter defaults" in result.output


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (_bindings(date.today() - timedelta(days=30)), "test-provider"),
        ("schema: 2\nharnesses: [unclosed\n", "invalid"),
    ],
)
def test_check_reports_stale_provider(config_dir: Path, content: str, expected: str) -> None:
    """A stale provider or an invalid file is reported without a traceback, exit 1."""
    (config_dir / "model-bindings.yaml").write_text(content)

    result = CliRunner().invoke(models_main, ["check"])

    assert result.exit_code == 1
    assert expected in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_check_json_lists_bindings(config_dir: Path) -> None:
    """--json returns path, status, stale providers and every binding; exit 0 when fresh."""
    (config_dir / "model-bindings.yaml").write_text(_bindings(date.today()))

    result = CliRunner().invoke(models_main, ["check", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["path"] == str(config_dir / "model-bindings.yaml")
    assert payload["status"] == "ok"
    assert payload["stale_providers"] == []
    assert payload["bindings"] == [
        {"harness": "codex-cli", "provider": "test-provider", "tier": "bulk", "model": "model-bulk"},
        {"harness": "codex-cli", "provider": "test-provider", "tier": "default", "model": "model-default"},
        {"harness": "codex-cli", "provider": "test-provider", "tier": "escalate-1", "model": "model-max"},
    ]
