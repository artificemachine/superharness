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


_TWO_HARNESSES = f"""schema: 2
providers:
  test-provider:
    verified: {date.today().isoformat()}
harnesses:
  codex-cli:
    default_provider: test-provider
    bindings:
      test-provider:
        default:
          id: codex-default
  pi:
    default_provider: test-provider
    bindings:
      test-provider:
        default:
          id: pi-default
"""


def _discovered(*ids: str) -> list:
    from datetime import datetime, timezone

    from superharness.engine.model_discovery import DiscoveredModel

    now = datetime.now(timezone.utc)
    return [DiscoveredModel(i, i, "native", "unknown", now) for i in ids]


def _probe(monkeypatch: pytest.MonkeyPatch, answer) -> list[tuple[str, list[str] | None]]:
    from superharness.engine import model_router

    calls: list[tuple[str, list[str] | None]] = []

    def _fake(agent, auth_mode="unknown", chain=None):
        calls.append((agent, chain))
        return answer(agent)

    monkeypatch.setattr(model_router, "_discover_for_agent", _fake)
    monkeypatch.setattr(model_router, "detect_auth_mode_for_agent", lambda a: "unknown")
    return calls


def _availability(output: str) -> dict[tuple[str, str], str]:
    rows = json.loads(output)["bindings"]
    return {(r["harness"], r["tier"]): r["availability"] for r in rows}


def test_check_probe_marks_dead_binding(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovery that answers without the bound model marks it unavailable; one probe per harness."""
    (config_dir / "model-bindings.yaml").write_text(_bindings(date.today()))
    calls = _probe(monkeypatch, lambda agent: _discovered("model-default", "other-model"))

    result = CliRunner().invoke(models_main, ["check", "--probe", "--json"])

    assert result.exit_code == 1, result.output
    assert _availability(result.output) == {
        ("codex-cli", "bulk"): "unavailable",
        ("codex-cli", "default"): "available",
        ("codex-cli", "escalate-1"): "unavailable",
    }
    assert [agent for agent, _ in calls] == ["codex-cli"]
    assert set(calls[0][1] or []) == {"model-bulk", "model-default", "model-max"}


def test_check_probe_unknown_when_discovery_empty(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery that cannot answer leaves every binding unknown, which is not a failure."""
    (config_dir / "model-bindings.yaml").write_text(_bindings(date.today()))
    _probe(monkeypatch, lambda agent: [])

    result = CliRunner().invoke(models_main, ["check", "--probe", "--json"])

    assert result.exit_code == 0, result.output
    assert set(_availability(result.output).values()) == {"unknown"}


def test_check_probe_survives_one_harness_failure(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One harness whose discovery raises is reported unknown with the error; others still report."""
    (config_dir / "model-bindings.yaml").write_text(_TWO_HARNESSES)

    def _answer(agent):
        if agent == "codex-cli":
            raise RuntimeError("probe crashed")
        return _discovered("pi-default")

    _probe(monkeypatch, _answer)

    result = CliRunner().invoke(models_main, ["check", "--probe", "--json"])

    assert result.exit_code == 0, result.output
    rows = {r["harness"]: r for r in json.loads(result.output)["bindings"]}
    assert rows["codex-cli"]["availability"] == "unknown"
    assert "probe crashed" in rows["codex-cli"]["error"]
    assert rows["pi"]["availability"] == "available"


def _manifest_first_choice(harness: str, tier: str) -> str:
    from superharness.engine.adapter_registry import load_manifest

    manifest = load_manifest(harness)
    chain = manifest.resolve_accept_chain(tier, "unknown")
    return chain[0] if chain else manifest.model_tiers[tier]["id"]


def test_init_writes_valid_schema2_from_manifests(config_dir: Path) -> None:
    """init writes a schema-2 file from the adapter manifests that dispatch then reads."""
    from superharness.engine import model_router
    from superharness.engine.model_bindings import load_bindings

    result = CliRunner().invoke(models_main, ["init"])

    assert result.exit_code == 0, result.output
    bindings = load_bindings(config_dir / "model-bindings.yaml")
    assert bindings.status == "ok"
    codex = bindings.data["harnesses"]["codex-cli"]
    assert codex["default_provider"] == "adapter-manifest"
    ladder = codex["bindings"]["adapter-manifest"]
    assert ladder["bulk"]["id"] == _manifest_first_choice("codex-cli", "mini")
    assert ladder["default"]["id"] == _manifest_first_choice("codex-cli", "standard")
    assert ladder["escalate-1"]["id"] == _manifest_first_choice("codex-cli", "max")
    assert model_router._resolve_runtime_binding_model("codex-cli", "standard") == ladder["default"]["id"]
    assert CliRunner().invoke(models_main, ["check"]).exit_code == 0


def test_init_refuses_existing_without_force(config_dir: Path) -> None:
    """An existing file is never overwritten without --force."""
    target = config_dir / "model-bindings.yaml"
    target.write_text("# operator file\n")

    result = CliRunner().invoke(models_main, ["init"])

    assert result.exit_code == 1
    assert target.read_text() == "# operator file\n"
    assert "--force" in result.output


def test_init_force_keeps_backup(config_dir: Path) -> None:
    """--force replaces the file and keeps a byte-identical timestamped backup."""
    target = config_dir / "model-bindings.yaml"
    target.write_bytes(b"# previous operator file\n")

    result = CliRunner().invoke(models_main, ["init", "--force"])

    assert result.exit_code == 0, result.output
    backups = list(config_dir.glob("model-bindings.yaml.bak-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"# previous operator file\n"
    assert "schema: 2" in target.read_text()


def test_init_failed_write_leaves_no_partial_file(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing final rename exits 1 and leaves neither a target nor a temporary file."""
    from superharness.commands import models

    def _fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(models.os, "replace", _fail)

    result = CliRunner().invoke(models_main, ["init"])

    assert result.exit_code == 1
    assert "disk full" in result.output
    assert list(config_dir.iterdir()) == []


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
