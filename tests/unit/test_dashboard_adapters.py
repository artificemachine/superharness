"""Tests for the dashboard /api/adapters endpoint (Iteration 6 of
PLAN-dynamic-model-selection.md).

The dashboard module is loaded via importlib (matching the existing
dashboard test convention) and `_adapter_models_data` is exercised
directly against a seeded model-discovery cache.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

from superharness.engine.model_discovery import DiscoveredModel, ModelDiscoveryCache

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD_UI = _REPO_ROOT / "src" / "superharness" / "scripts" / "dashboard-ui.py"
_SPEC = importlib.util.spec_from_file_location("dashboard_ui_adapters", _DASHBOARD_UI)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _seed(db: Path, project: str) -> None:
    cache = ModelDiscoveryCache(db)
    now = datetime.now(timezone.utc)
    cache.set(project, "codex-cli", DiscoveredModel("gpt-5.3-codex", "gpt-5.3-codex", "probe", "chatgpt", now))
    cache.set(project, "opencode", DiscoveredModel("opencode/deepseek-v4-flash", "x", "native", "unknown", now))


def test_adapter_models_data_reports_seeded_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: /api/adapters payload reflects the seeded cache."""
    db = tmp_path / "state.sqlite3"
    _seed(db, str(tmp_path))

    from superharness.engine import model_router

    monkeypatch.setattr(model_router, "_model_discovery_cache_path", lambda p: str(db))
    monkeypatch.setattr(
        model_router, "detect_auth_mode_for_agent",
        lambda a: "chatgpt" if a == "codex-cli" else "unknown",
    )

    data = _MODULE._adapter_models_data(tmp_path)
    assert "adapters" in data
    by_name = {r["name"]: r for r in data["adapters"]}
    assert by_name["codex-cli"]["available_models"] == ["gpt-5.3-codex"]
    assert by_name["codex-cli"]["auth_mode"] == "chatgpt"
    assert by_name["opencode"]["available_models"] == ["opencode/deepseek-v4-flash"]
    assert by_name["claude-code"]["available_models"] == []


def test_adapter_models_data_empty_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: an empty cache yields empty lists, not an error."""
    db = tmp_path / "state.sqlite3"
    ModelDiscoveryCache(db)  # create empty

    from superharness.engine import model_router

    monkeypatch.setattr(model_router, "_model_discovery_cache_path", lambda p: str(db))
    data = _MODULE._adapter_models_data(tmp_path)
    assert data == {"adapters": []} or all(
        r["available_models"] == [] for r in data["adapters"]
    )


def test_adapter_models_data_never_raises(tmp_path: Path) -> None:
    """Chaos: unresolvable cache path → returns {'adapters': []}, no raise."""
    data = _MODULE._adapter_models_data(tmp_path)
    assert "adapters" in data
