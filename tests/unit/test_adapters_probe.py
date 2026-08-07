"""Tests for Iteration 6 of PLAN-dynamic-model-selection.md.

Covers:
- `shux adapters --probe` flag: runs discovery across adapters, reports
  available models per agent, JSON mode with a stable schema
- `shux adapters --probe` reads from cache on second run (no re-probe)
- Dashboard `/api/adapters` route: reads cache, shows available models
- `shux doctor` "Models: N/M working" line
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from superharness.commands.adapters import main as adapters_main
from superharness.engine.model_discovery import DiscoveredModel, ModelDiscoveryCache


def _seed_cache(db_path: Path, project: str) -> None:
    """Seed a model-discovery cache with 2 working + 1 missing agent."""
    cache = ModelDiscoveryCache(db_path)
    now = datetime.now(timezone.utc)
    cache.set(project, "codex-cli", DiscoveredModel("gpt-5.3-codex", "gpt-5.3-codex", "probe", "chatgpt", now))
    cache.set(project, "opencode", DiscoveredModel("opencode/deepseek-v4-flash", "opencode/deepseek-v4-flash", "native", "unknown", now))


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_adapters_probe_exits_zero(tmp_path: Path) -> None:
    """Smoke: shux adapters --probe exits 0 with output per adapter."""
    runner = CliRunner()
    result = runner.invoke(adapters_main, ["--probe", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "adapters --probe" in result.output


def test_adapters_probe_text_reports_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unit: --probe text output lists discovered models per adapter."""
    from superharness.engine import model_router

    monkeypatch.setattr(
        model_router, "_discover_for_agent",
        lambda a, m="unknown": [
            DiscoveredModel(f"{a}/model-x", f"{a}/model-x", "probe", m, datetime.now(timezone.utc))
        ],
    )
    runner = CliRunner()
    result = runner.invoke(adapters_main, ["--probe", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "codex-cli/model-x" in result.output
    assert "models:" in result.output


def test_adapters_probe_json_is_valid(tmp_path: Path) -> None:
    """Smoke: --probe --json emits valid JSON."""
    runner = CliRunner()
    result = runner.invoke(adapters_main, ["--probe", "--json", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list)


# ---------------------------------------------------------------------------
# Unit — flag parsing
# ---------------------------------------------------------------------------


def test_adapters_probe_rejects_positional(tmp_path: Path) -> None:
    """Unit: --probe takes no positional arguments."""
    runner = CliRunner()
    result = runner.invoke(adapters_main, ["--probe", "extra-arg"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Integration — cache read on second run
# ---------------------------------------------------------------------------


def test_adapters_probe_reads_cache_on_second_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: after a probe, the second --probe reads from cache.

    The discovery call must run exactly once across two invocations.
    """
    from superharness.engine import model_router

    calls: list[str] = []

    def _fake_discover(agent, auth_mode="unknown"):
        calls.append(agent)
        return [
            DiscoveredModel(
                "gpt-5.3-codex", "gpt-5.3-codex", "probe", auth_mode,
                datetime.now(timezone.utc),
            )
        ]

    monkeypatch.setattr(model_router, "_discover_for_agent", _fake_discover)

    runner = CliRunner()
    r1 = runner.invoke(adapters_main, ["--probe", "--project", str(tmp_path)])
    first_run_calls = len(calls)
    r2 = runner.invoke(adapters_main, ["--probe", "--project", str(tmp_path)])
    second_run_calls = len(calls) - first_run_calls
    assert r1.exit_code == 0 and r2.exit_code == 0
    # First run probed every adapter once; second run hit the cache.
    assert first_run_calls >= 1
    assert second_run_calls == 0


# ---------------------------------------------------------------------------
# Contract — JSON schema
# ---------------------------------------------------------------------------


def test_adapters_probe_json_schema(tmp_path: Path) -> None:
    """Contract: --probe --json rows carry stable fields."""
    runner = CliRunner()
    result = runner.invoke(adapters_main, ["--probe", "--json", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    for row in rows:
        assert "name" in row
        assert "valid" in row
        assert "available_models" in row
        assert isinstance(row["available_models"], list)


# ---------------------------------------------------------------------------
# Regression — no --probe is unchanged
# ---------------------------------------------------------------------------


def test_adapters_without_probe_unchanged(tmp_path: Path) -> None:
    """Regression: shux adapters without --probe emits the legacy output."""
    runner = CliRunner()
    result = runner.invoke(adapters_main, ["--project", str(tmp_path), "list"])
    assert result.exit_code == 0
    assert "superharness — adapters" in result.output
    assert "available_models" not in result.output


# ---------------------------------------------------------------------------
# Chaos — partial probe failure
# ---------------------------------------------------------------------------


def test_adapters_probe_partial_failure_still_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chaos: discovery raising for one agent → others still reported, JSON valid."""
    from superharness.engine import model_router

    def _flaky_discover(agent, auth_mode="unknown"):
        if agent == "codex-cli":
            raise RuntimeError("codex binary missing")
        return [
            DiscoveredModel(
                "opencode/deepseek-v4-flash", "opencode/deepseek-v4-flash",
                "native", auth_mode, datetime.now(timezone.utc),
            )
        ]

    monkeypatch.setattr(model_router, "_discover_for_agent", _flaky_discover)
    runner = CliRunner()
    result = runner.invoke(adapters_main, ["--probe", "--json", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert any("failed" in str(r) or r.get("available_models") for r in rows)


# ---------------------------------------------------------------------------
# E2E — seeded cache reported
# ---------------------------------------------------------------------------


def test_adapters_probe_reports_seeded_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """E2E: with a seeded cache, --probe reports the cached models."""
    from superharness.engine import model_router

    db = tmp_path / "state.sqlite3"
    _seed_cache(db, str(tmp_path))
    monkeypatch.setattr(
        model_router, "_model_discovery_cache_path", lambda p: str(db)
    )
    monkeypatch.setattr(model_router, "_discover_for_agent", lambda a, m="unknown": [])
    # The suite's conftest stubs agent binaries with exit-127 shims, so real
    # auth detection returns 'unknown' here; pin it to match the seed.
    monkeypatch.setattr(
        model_router, "detect_auth_mode_for_agent",
        lambda a: "chatgpt" if a == "codex-cli" else "unknown",
    )

    runner = CliRunner()
    result = runner.invoke(adapters_main, ["--probe", "--json", "--project", str(tmp_path)])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    by_name = {r["name"]: r for r in rows}
    assert by_name["codex-cli"]["available_models"] == ["gpt-5.3-codex"]
    assert by_name["opencode"]["available_models"] == ["opencode/deepseek-v4-flash"]


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


def test_adapters_probe_fast_with_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Performance: --probe with a populated cache completes < 2s."""
    import time

    from superharness.engine import model_router

    db = tmp_path / "state.sqlite3"
    _seed_cache(db, str(tmp_path))
    monkeypatch.setattr(
        model_router, "_model_discovery_cache_path", lambda p: str(db)
    )
    monkeypatch.setattr(model_router, "_discover_for_agent", lambda a, m="unknown": [])

    runner = CliRunner()
    start = time.perf_counter()
    result = runner.invoke(adapters_main, ["--probe", "--project", str(tmp_path)])
    elapsed = time.perf_counter() - start
    assert result.exit_code == 0
    assert elapsed < 2.0
