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
    sr._cached_pricing = None
    yield
    mr._cached_map = None
    sr._cached_pricing = None

# ---------------------------------------------------------------------------
# R3 Tests
# ---------------------------------------------------------------------------

def test_resolve_model_returns_haiku_baseline():
    """1. resolve_model('claude-code', 'mini') returns 'haiku' (no config file present)"""
    # Note: 'haiku' is the baseline from the original hardcoded MODEL_MAP
    assert resolve_model("claude-code", "mini") == "haiku"

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
    # codex-cli.mini is still from default (gpt-5.2 in the handoff spec, but check what we put in engine/models.yaml)
    assert resolve_model("codex-cli", "mini", project_dir=str(tmp_project)) == "gpt-5.2"

def test_missing_config_falls_back_to_hardcoded():
    """4. deleting models.yaml falls back gracefully, no exception"""
    # If no YAML files exist at all (bundled or project), it should use hardcoded MODEL_MAP
    # (Assuming we haven't created the bundled one yet in this test environment if we mock it, 
    # but here we just ensure it doesn't crash)
    assert resolve_model("claude-code", "standard") == "sonnet"

def test_corrupt_config_falls_back(tmp_project):
    """5. invalid YAML in models.yaml falls back silently"""
    models_yaml = tmp_project / ".superharness" / "models.yaml"
    models_yaml.write_text("!!corrupt {")
    
    assert resolve_model("claude-code", "max", project_dir=str(tmp_project)) == "opus"

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
    # claude-code.standard should still be 'sonnet' from bundled default
    assert resolve_model("claude-code", "standard", project_dir=str(tmp_project)) == "sonnet"

def test_bundled_yaml_is_primary_source(monkeypatch, tmp_path):
    """9. bundled engine/models.yaml used when no project override"""
    # We'll mock the bundled path
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    bundled_yaml = bundled_dir / "models.yaml"
    bundled_yaml.write_text(yaml.dump({
        "model_map": {
            "claude-code": {
                "mini": "bundled-mini"
            }
        }
    }))
    
    import superharness.engine.model_router as mr
    import importlib.resources
    
    # Mock importlib.resources.files
    class MockTraversable:
        def __init__(self, path): self.path = path
        def joinpath(self, name): return MockTraversable(self.path / name)
        def open(self, mode="r"): return open(self.path, mode)
        def __truediv__(self, other): return self.joinpath(other)
    
    monkeypatch.setattr("importlib.resources.files", lambda pkg: MockTraversable(bundled_dir.parent if pkg == "superharness" else None))

    assert resolve_model("claude-code", "mini") == "bundled-mini"

def test_project_yaml_takes_precedence_over_bundled(monkeypatch, tmp_path, tmp_project):
    """10. project file wins over bundled"""
    bundled_dir = tmp_path / "bundled"
    bundled_dir.mkdir()
    (bundled_dir / "models.yaml").write_text(yaml.dump({
        "model_map": {"claude-code": {"mini": "bundled"}}
    }))
    
    models_yaml = tmp_project / ".superharness" / "models.yaml"
    models_yaml.write_text(yaml.dump({
        "model_map": {"claude-code": {"mini": "project"}}
    }))
    
    # Mock bundled same as above
    class MockTraversable:
        def __init__(self, path): self.path = path
        def joinpath(self, name): return MockTraversable(self.path / name)
        def open(self, mode="r"): return open(self.path, mode)
        def __truediv__(self, other): return self.joinpath(other)
    monkeypatch.setattr("importlib.resources.files", lambda pkg: MockTraversable(bundled_dir.parent))

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
    # Should use bundled/hardcoded
    assert resolve_model("claude-code", "standard") == "sonnet"
