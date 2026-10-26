"""Tests for `shux models refresh` and its receipts (engine/model_refresh.py)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from superharness.commands.models import main as models_main
from superharness.engine.model_refresh import RECEIPTS_FILENAME, last_receipt

_SAMPLE = {"anthropic": {"models": {
    "claude-haiku-4-5": {"id": "claude-haiku-4-5", "family": "claude-haiku",
                         "release_date": "2025-10-15"},
    "claude-haiku-5-5": {"id": "claude-haiku-5-5", "family": "claude-haiku",
                         "release_date": "2026-10-07"},
    "claude-sonnet-5": {"id": "claude-sonnet-5", "family": "claude-sonnet",
                        "release_date": "2026-06-29"},
    "claude-sonnet-5-5": {"id": "claude-sonnet-5-5", "family": "claude-sonnet",
                          "release_date": "2026-09-28"},
}}}


def _bindings(verified: date, default_model: str = "claude-sonnet-5-5") -> str:
    return f"""schema: 2
providers:
  anthropic:
    verified: {verified.isoformat()}
harnesses:
  claude-code:
    default_provider: anthropic
    bindings:
      anthropic:
        bulk:
          id: claude-haiku-4-5
        default:
          id: {default_model}
"""


@pytest.fixture
def dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    config = tmp_path / "config"
    state = tmp_path / "state"
    config.mkdir()
    monkeypatch.setenv("SUPERHARNESS_CONFIG_DIR", str(config))
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(state))
    return config, state


def _stub_network(monkeypatch: pytest.MonkeyPatch, catalog, discovered: tuple[str, ...]) -> list[str]:
    """Replace the catalog fetch, the docs checker and harness discovery; record network use."""
    from datetime import datetime as _dt

    from superharness.engine import model_catalog, model_router
    from superharness.engine.model_discovery import DiscoveredModel

    calls: list[str] = []

    def _fetch(*args, **kwargs):
        calls.append("catalog")
        return catalog

    class _Docs:
        def check(self, provider, model_id):
            calls.append("docs")
            return model_catalog.DocsCheck("confirmed")

    def _discover(agent, auth_mode="unknown", chain=None):
        calls.append("discovery")
        now = _dt.now(timezone.utc)
        return [DiscoveredModel(i, i, "native", "unknown", now) for i in discovered]

    monkeypatch.setattr(model_catalog, "fetch_catalog", _fetch)
    monkeypatch.setattr(model_catalog, "DocsChecker", lambda **kwargs: _Docs())
    monkeypatch.setattr(model_router, "_discover_for_agent", _discover)
    monkeypatch.setattr(model_router, "detect_auth_mode_for_agent", lambda a: "unknown")
    return calls


def _receipts(state: Path) -> list[dict]:
    path = state / RECEIPTS_FILENAME
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_refresh_skips_without_network_when_fresh(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fresh bindings: no catalog, docs or discovery call; one `skipped` receipt; exit 0."""
    from superharness.engine.model_catalog import parse_catalog

    config, state = dirs
    (config / "model-bindings.yaml").write_text(_bindings(date.today()))
    calls = _stub_network(monkeypatch, parse_catalog(_SAMPLE), ("claude-haiku-5-5",))

    result = CliRunner().invoke(models_main, ["refresh"])

    assert result.exit_code == 0, result.output
    assert calls == []
    receipts = _receipts(state)
    assert len(receipts) == 1
    assert receipts[0]["outcome"] == "skipped"
    assert set(receipts[0]) == {"at", "outcome", "applied", "skipped", "errors"}


def test_refresh_applies_and_records_ok(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale provider with a confirmed candidate: the file is updated, receipt `ok`, exit 0."""
    from superharness.engine.model_catalog import parse_catalog

    config, state = dirs
    target = config / "model-bindings.yaml"
    target.write_text(_bindings(date.today() - timedelta(days=30)))
    _stub_network(monkeypatch, parse_catalog(_SAMPLE), ("claude-haiku-5-5",))

    result = CliRunner().invoke(models_main, ["refresh"])

    assert result.exit_code == 0, result.output
    assert "id: claude-haiku-5-5" in target.read_text()
    receipt = _receipts(state)[-1]
    assert receipt["outcome"] == "ok"
    assert receipt["applied"] == ["claude-code bulk claude-haiku-4-5 -> claude-haiku-5-5"]
    assert receipt["skipped"] == []
    assert last_receipt() == receipt


def test_refresh_records_partial_when_candidates_skipped(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate the harness does not list is skipped and named; receipt `partial`, exit 0."""
    from superharness.engine.model_catalog import parse_catalog

    config, state = dirs
    target = config / "model-bindings.yaml"
    target.write_text(_bindings(date.today() - timedelta(days=30), default_model="claude-sonnet-5"))
    # The harness lists haiku 5.5 but not sonnet 5.5.
    _stub_network(monkeypatch, parse_catalog(_SAMPLE), ("claude-haiku-5-5",))

    result = CliRunner().invoke(models_main, ["refresh"])

    assert result.exit_code == 0, result.output
    receipt = _receipts(state)[-1]
    assert receipt["outcome"] == "partial"
    assert receipt["applied"] == ["claude-code bulk claude-haiku-4-5 -> claude-haiku-5-5"]
    assert receipt["skipped"] == ["claude-code default claude-sonnet-5 -> claude-sonnet-5-5"]
    assert "id: claude-sonnet-5\n" in target.read_text()


def test_refresh_failure_exits_1_and_records_failed(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable catalog: nothing written, receipt `failed` with the reason, exit 1."""
    from superharness.engine.model_catalog import CatalogFailure

    config, state = dirs
    target = config / "model-bindings.yaml"
    target.write_text(_bindings(date.today() - timedelta(days=30)))
    before = target.read_bytes()
    _stub_network(monkeypatch, CatalogFailure("models.dev", "cannot reach models.dev: offline"), ())

    result = CliRunner().invoke(models_main, ["refresh"])

    assert result.exit_code == 1
    assert target.read_bytes() == before
    receipts = _receipts(state)
    assert len(receipts) == 1
    assert receipts[0]["outcome"] == "failed"
    assert receipts[0]["errors"] == {"models.dev": "cannot reach models.dev: offline"}


def test_refresh_missing_bindings_records_failed(
    dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No bindings file: receipt `failed`, exit 1, no bindings file created, no network."""
    config, state = dirs
    calls = _stub_network(monkeypatch, {}, ())

    result = CliRunner().invoke(models_main, ["refresh"])

    assert result.exit_code == 1
    assert not (config / "model-bindings.yaml").exists()
    assert calls == []
    receipt = _receipts(state)[-1]
    assert receipt["outcome"] == "failed"
    assert "bindings" in receipt["errors"]


def test_last_receipt_ignores_malformed_lines(dirs: tuple[Path, Path]) -> None:
    """A torn or foreign last line does not hide the previous valid receipt."""
    _, state = dirs
    state.mkdir()
    valid = {"at": datetime.now(timezone.utc).isoformat(), "outcome": "ok",
             "applied": [], "skipped": [], "errors": {}}
    (state / RECEIPTS_FILENAME).write_text(json.dumps(valid) + "\n{torn\n[1, 2]\n")

    assert last_receipt() == valid
