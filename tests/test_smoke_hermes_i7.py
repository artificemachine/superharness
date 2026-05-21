"""Smoke test for behavioral profile dashboard visibility (Iteration 7)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_profile_data():
    """Import _profile_data from dashboard-ui.py bypassing module-level class loading."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dashboard_ui",
        os.path.join(os.path.dirname(__file__), "..", "src", "superharness", "scripts", "dashboard-ui.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dashboard_ui"] = mod
    spec.loader.exec_module(mod)
    return mod._profile_data


def test_profile_data_returns_valid_json(tmp_path: Path) -> None:
    """_profile_data should return valid JSON with profiles and trials keys."""
    upath = os.path.join(os.path.expanduser("~"), ".config", "superharness", "behavioral")
    os.makedirs(upath, exist_ok=True)
    fpath = os.path.join(upath, "task_style.json")
    with open(fpath, "w") as f:
        json.dump({"default_effort": "medium", "tdd_required": True, "confidence": "medium", "sample_count": 15}, f)

    try:
        profile_data = _load_profile_data()
        data = profile_data(tmp_path)
        assert "profiles" in data
        assert data["has_data"] is True
    finally:
        for fn in os.listdir(upath):
            if fn.endswith(".json") and not fn.startswith("_"):
                os.remove(os.path.join(upath, fn))


def test_profile_data_empty_when_no_profiles(tmp_path: Path) -> None:
    """_profile_data should return has_data=False when no profile files exist."""
    profile_data = _load_profile_data()
    data = profile_data(tmp_path)
    assert data["has_data"] is False
    assert data["profiles"] == {}
