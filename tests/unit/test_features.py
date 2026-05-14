"""Tests for features.json generation and hygiene validation."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.helpers import REPO_ROOT, seed_sqlite_from_yaml


def _run_init(cwd, args: list[str], env: dict | None = None):
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(REPO_ROOT / "src")
    if env:
        merged.update(env)
    cmd = [sys.executable, "-m", "superharness.commands.init_project"] + args
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=merged, check=False)


def _run_validate(cwd, args: list[str]):
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.engine.validate"] + args
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=merged, check=False)


def _write_harness(project: Path, features: list[dict] | None = None):
    """Create minimal .superharness/ for hygiene tests."""
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text("id: test\ntasks: []\ndecisions: []\nfailures: []\n")
    (harness / "ledger.md").write_text("# Ledger\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    if features is not None:
        (harness / "features.json").write_text(json.dumps({"features": features}, indent=2) + "\n")
    seed_sqlite_from_yaml(project)


# ---------------------------------------------------------------------------
# Init generates features.json
# ---------------------------------------------------------------------------


class TestInitGeneratesFeatures:
    def test_init_creates_features_json(self, tmp_path):
        project = tmp_path / "myproj"
        project.mkdir()
        r = _run_init(project, ["MyProject", "Python", "active"])
        assert r.returncode == 0, r.stderr
        features_file = project / ".superharness" / "features.json"
        assert features_file.exists()
        doc = json.loads(features_file.read_text())
        assert "features" in doc
        assert len(doc["features"]) >= 3
        # All features start with passes: false
        for feat in doc["features"]:
            assert feat["passes"] is False

    def test_init_python_stack_adds_pip_feature(self, tmp_path):
        project = tmp_path / "pyproj"
        project.mkdir()
        _run_init(project, ["PyProject", "Python/Django", "active"])
        doc = json.loads((project / ".superharness" / "features.json").read_text())
        ids = [f["id"] for f in doc["features"]]
        assert "pip-install" in ids

    def test_init_docker_stack_adds_docker_feature(self, tmp_path):
        project = tmp_path / "dkproj"
        project.mkdir()
        _run_init(project, ["DkProject", "Node/Docker", "active"])
        doc = json.loads((project / ".superharness" / "features.json").read_text())
        ids = [f["id"] for f in doc["features"]]
        assert "docker-build" in ids

    def test_features_schema_valid(self, tmp_path):
        project = tmp_path / "schematest"
        project.mkdir()
        _run_init(project, ["Test", "Go", "active"])
        doc = json.loads((project / ".superharness" / "features.json").read_text())
        for feat in doc["features"]:
            assert "id" in feat
            assert "category" in feat
            assert "description" in feat
            assert "steps" in feat
            assert isinstance(feat["steps"], list)
            assert "passes" in feat
            assert isinstance(feat["passes"], bool)


# ---------------------------------------------------------------------------
# Hygiene validates features.json
# ---------------------------------------------------------------------------


class TestHygieneValidatesFeatures:
    def test_hygiene_passes_valid_features(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_harness(project, features=[
            {"id": "f1", "category": "core", "description": "test", "steps": [], "passes": False},
        ])
        r = _run_validate(REPO_ROOT, ["--project", str(project)])
        assert r.returncode == 0, r.stdout

    def test_hygiene_catches_duplicate_ids(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_harness(project, features=[
            {"id": "f1", "category": "core", "description": "a", "steps": [], "passes": False},
            {"id": "f1", "category": "core", "description": "b", "steps": [], "passes": False},
        ])
        r = _run_validate(REPO_ROOT, ["--project", str(project)])
        assert r.returncode == 1
        assert "duplicate feature id" in r.stdout

    def test_hygiene_catches_missing_passes_field(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_harness(project, features=[
            {"id": "f1", "category": "core", "description": "a", "steps": []},
        ])
        r = _run_validate(REPO_ROOT, ["--project", str(project)])
        assert r.returncode == 1
        assert "missing boolean 'passes' field" in r.stdout

    def test_hygiene_skips_when_no_features_file(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_harness(project, features=None)
        r = _run_validate(REPO_ROOT, ["--project", str(project)])
        assert r.returncode == 0

    def test_hygiene_catches_invalid_json(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        _write_harness(project)
        (project / ".superharness" / "features.json").write_text("{invalid json")
        r = _run_validate(REPO_ROOT, ["--project", str(project)])
        assert r.returncode == 1
        assert "invalid JSON" in r.stdout
