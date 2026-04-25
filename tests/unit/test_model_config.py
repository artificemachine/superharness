from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
import yaml

from superharness.engine.model_router import resolve_model, _load_model_map
from superharness.engine.sdk_runner import _calculate_cost, _load_pricing

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory with a .superharness folder."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".superharness").mkdir()
    return project

@pytest.fixture(autouse=True)
def reset_caches():
    """Reset module-level caches before each test."""
    import superharness.engine.model_router as mr
    import superharness.engine.sdk_runner as sr
    mr._cached_map = None
    mr._cached_project_maps = {}
    sr._cached_pricing = None
    yield
    mr._cached_map = None
    mr._cached_project_maps = {}
    sr._cached_pricing = None

# ---------------------------------------------------------------------------
# R3 Tests
# ---------------------------------------------------------------------------

def test_resolve_model_returns_haiku_baseline():
    """1. resolve_model('claude-code', 'mini') returns the canonical haiku model ID."""
    assert resolve_model("claude-code", "mini") == "claude-haiku-4-5-20251001"

def test_project_override_changes_model(tmp_project):
    """2. .superharness/models.yaml with claude-code.mini: my-model overrides the bundled default"""
    models_yaml = tmp_project / ".superharness" / "models.yaml"
    models_yaml.write_text(yaml.dump({
        "model_map": {
            "claude-code": {
                "mini": "my-model"
            }
        }
    }))
    
    # We pass the project_dir to resolve_model (it should support this now)
    assert resolve_model("claude-code", "mini", project_dir=str(tmp_project)) == "my-model"

def test_partial_override_preserves_others(tmp_project):
    """3. overriding only claude-code.mini keeps codex-cli mappings intact"""
    models_yaml = tmp_project / ".superharness" / "models.yaml"
    models_yaml.write_text(yaml.dump({
        "model_map": {
            "claude-code": {
                "mini": "overridden"
            }
        }
    }))
    
    # claude-code.mini is overridden
    assert resolve_model("claude-code", "mini", project_dir=str(tmp_project)) == "overridden"
    # codex-cli.mini is still from default
    assert resolve_model("codex-cli", "mini", project_dir=str(tmp_project)) == "gpt-5.1-codex-mini"

def test_missing_config_falls_back_to_hardcoded():
    """4. deleting models.yaml falls back gracefully, no exception"""
    assert resolve_model("claude-code", "standard") == "claude-sonnet-4-6"

def test_corrupt_config_falls_back(tmp_project):
    """5. invalid YAML in models.yaml falls back silently"""
    models_yaml = tmp_project / ".superharness" / "models.yaml"
    models_yaml.write_text("!!corrupt {")
    
    assert resolve_model("claude-code", "max", project_dir=str(tmp_project)) == "claude-opus-4-7"

def test_pricing_loads_from_yaml(tmp_project):
    """6. pricing dict loaded from models.yaml when present"""
    models_yaml = tmp_project / ".superharness" / "models.yaml"
    models_yaml.write_text(yaml.dump({
        "pricing": {
            "custom-model": {
                "input": 1.0,
                "output": 2.0
            }
        }
    }))
    
    # cost for 1M tokens each: 1.0 + 2.0 = 3.0
    cost = _calculate_cost("custom-model", 1_000_000, 1_000_000, project_dir=str(tmp_project))
    assert cost == 3.0

def test_pricing_falls_back_to_hardcoded():
    """7. no models.yaml -> hardcoded pricing unchanged"""
    # claude-sonnet-4-6: input 3.0, output 15.0
    cost = _calculate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert cost == 18.0

def test_deep_merge_preserves_unoverridden_keys(tmp_project):
    """8. project override merges at agent level, not replaces"""
    models_yaml = tmp_project / ".superharness" / "models.yaml"
    models_yaml.write_text(yaml.dump({
        "model_map": {
            "claude-code": {
                "mini": "new-mini"
            }
        }
    }))
    
    # claude-code.mini is new
    assert resolve_model("claude-code", "mini", project_dir=str(tmp_project)) == "new-mini"
    # claude-code.standard should still be canonical sonnet from bundled default
    assert resolve_model("claude-code", "standard", project_dir=str(tmp_project)) == "claude-sonnet-4-6"

def test_bundled_yaml_is_primary_source(monkeypatch, tmp_path):
    """9. bundled engine/models.yaml used when no project override"""
    # files("superharness").joinpath("engine/models.yaml") resolves to tmp_path/engine/models.yaml
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    (engine_dir / "models.yaml").write_text(yaml.dump({
        "model_map": {
            "claude-code": {
                "mini": "bundled-mini"
            }
        }
    }))

    class MockTraversable:
        def __init__(self, path): self.path = path
        def joinpath(self, name): return MockTraversable(self.path / Path(name))
        def open(self, mode="r"): return open(self.path, mode)
        def __truediv__(self, other): return self.joinpath(other)

    monkeypatch.setattr("importlib.resources.files", lambda pkg: MockTraversable(tmp_path))

    assert resolve_model("claude-code", "mini") == "bundled-mini"

def test_project_yaml_takes_precedence_over_bundled(monkeypatch, tmp_path, tmp_project):
    """10. project file wins over bundled"""
    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    (engine_dir / "models.yaml").write_text(yaml.dump({
        "model_map": {"claude-code": {"mini": "bundled"}}
    }))

    models_yaml = tmp_project / ".superharness" / "models.yaml"
    models_yaml.write_text(yaml.dump({
        "model_map": {"claude-code": {"mini": "project"}}
    }))

    class MockTraversable:
        def __init__(self, path): self.path = path
        def joinpath(self, name): return MockTraversable(self.path / Path(name))
        def open(self, mode="r"): return open(self.path, mode)
        def __truediv__(self, other): return self.joinpath(other)
    monkeypatch.setattr("importlib.resources.files", lambda pkg: MockTraversable(tmp_path))

    assert resolve_model("claude-code", "mini", project_dir=str(tmp_project)) == "project"

def test_load_is_cached(tmp_project, monkeypatch):
    """11. second call to _load_model_map() doesn't re-read disk (module-level cache)"""
    models_yaml = tmp_project / ".superharness" / "models.yaml"
    models_yaml.write_text(yaml.dump({"model_map": {"claude-code": {"mini": "v1"}}}))
    
    # First load
    assert resolve_model("claude-code", "mini", project_dir=str(tmp_project)) == "v1"
    
    # Change file on disk
    models_yaml.write_text(yaml.dump({"model_map": {"claude-code": {"mini": "v2"}}}))
    
    # Second load should still return v1
    assert resolve_model("claude-code", "mini", project_dir=str(tmp_project)) == "v1"

def test_resolve_model_no_project_dir():
    """12. resolve_model('claude-code', 'standard') works when called without project_dir arg"""
    assert resolve_model("claude-code", "standard") == "claude-sonnet-4-6"
