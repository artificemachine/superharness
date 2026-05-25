"""Guard: every YAML in the project must be classified in state_manifest.yaml.

Structural fix from bulletproof v8. The pattern of "find a new YAML each audit
that nobody knew was state" stops here: adding any .yaml/.yml anywhere in the
tree fails CI until state_manifest.yaml lists it (explicit or pattern match).

Classifications enforced:
  - state    → must have backed_by (SQLite table name); existence of the table
               is asserted at module level by importing the corresponding DAO.
  - boundary → must have ingest_function (qualified Python path); we don't import
               it (avoids heavy startup) but require the string to be present.
  - config | template | ignore → free; no further check.

Run: pytest tests/test_yaml_manifest_complete.py -q
"""
from __future__ import annotations

import fnmatch
import os
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "state_manifest.yaml"

# Directories we always skip — anything inside is out of scope.
# These match `.gitignore`-like behavior; the manifest doesn't need to enumerate
# every transient file under these paths.
_SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
}

# Valid classification types
_VALID_TYPES = {"config", "state", "boundary", "template", "ignore"}


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        pytest.fail(f"state_manifest.yaml missing at {MANIFEST_PATH}")
    with MANIFEST_PATH.open() as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        pytest.fail("state_manifest.yaml is not a dict")
    return doc


def _walk_yamls() -> list[Path]:
    """Return every .yaml/.yml file in the tree, repo-relative paths."""
    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        # Prune skip dirs
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if fname.endswith((".yaml", ".yml")):
                full = Path(dirpath) / fname
                results.append(full.relative_to(REPO_ROOT))
    return sorted(results)


def _classify(rel_path: Path, files: dict[str, dict], patterns: list[dict]) -> dict | None:
    """Return the manifest entry for a path, or None if unclassified."""
    s = str(rel_path)
    # Explicit file wins
    if s in files:
        return files[s]
    # Patterns in order
    for entry in patterns:
        glob = entry.get("glob")
        if not glob:
            continue
        if fnmatch.fnmatch(s, glob):
            return entry
    return None


def test_manifest_structure_valid():
    """The manifest file is parseable and has the right shape."""
    doc = _load_manifest()
    assert doc.get("version") == 1, "manifest version must be 1"
    files = doc.get("files", [])
    patterns = doc.get("patterns", [])
    assert isinstance(files, list), "files must be a list"
    assert isinstance(patterns, list), "patterns must be a list"
    for entry in files:
        assert "path" in entry, f"file entry missing path: {entry}"
        assert "type" in entry, f"file entry missing type: {entry}"
        assert entry["type"] in _VALID_TYPES, (
            f"file entry has invalid type {entry['type']!r}: {entry}"
        )
        assert "reason" in entry, f"file entry missing reason: {entry}"
    for entry in patterns:
        assert "glob" in entry, f"pattern entry missing glob: {entry}"
        assert "type" in entry, f"pattern entry missing type: {entry}"
        assert entry["type"] in _VALID_TYPES, (
            f"pattern entry has invalid type {entry['type']!r}: {entry}"
        )
        assert "reason" in entry, f"pattern entry missing reason: {entry}"


def test_every_yaml_is_classified():
    """Every .yaml/.yml in the repo must be classified by the manifest."""
    doc = _load_manifest()
    files_by_path = {e["path"]: e for e in doc.get("files", [])}
    patterns = doc.get("patterns", [])

    unclassified: list[str] = []
    for rel in _walk_yamls():
        # Skip the manifest itself
        if str(rel) == "state_manifest.yaml":
            continue
        entry = _classify(rel, files_by_path, patterns)
        if entry is None:
            unclassified.append(str(rel))

    assert not unclassified, (
        "Unclassified YAML files — add each to state_manifest.yaml with a type "
        "(config|state|boundary|template|ignore) and a one-line reason:\n  "
        + "\n  ".join(unclassified)
    )


def test_state_files_have_sqlite_backing():
    """Any 'state' classified YAML must declare backed_by (a SQLite table)."""
    doc = _load_manifest()
    bad: list[str] = []
    for entry in doc.get("files", []) + doc.get("patterns", []):
        if entry.get("type") != "state":
            continue
        if not entry.get("backed_by"):
            label = entry.get("path") or entry.get("glob")
            bad.append(f"{label} — missing backed_by (SQLite table name)")
    assert not bad, (
        "State YAMLs must name a SQLite SoT table:\n  " + "\n  ".join(bad)
    )


def test_boundary_files_have_ingest_function():
    """Any 'boundary' classified YAML must declare an ingest_function."""
    doc = _load_manifest()
    bad: list[str] = []
    for entry in doc.get("files", []) + doc.get("patterns", []):
        if entry.get("type") != "boundary":
            continue
        if not entry.get("ingest_function"):
            label = entry.get("path") or entry.get("glob")
            bad.append(f"{label} — missing ingest_function")
    assert not bad, (
        "Boundary YAMLs must name an ingest function:\n  " + "\n  ".join(bad)
    )


def test_state_backing_tables_are_real():
    """Every 'state' entry's backed_by table must exist in a known DAO module.

    We check by importing each DAO module — fail fast if a DAO is missing.
    """
    sys.path.insert(0, str(REPO_ROOT / "src"))
    doc = _load_manifest()
    # Map: SQLite table → DAO module that should exist
    table_to_dao = {
        "agent_heartbeats": "superharness.engine.watcher_heartbeat_dao",
        "agent_runtime_status": "superharness.engine.agent_runtime_status_dao",
        "agent_pulses": "superharness.engine.agent_pulse_dao",
        "onboarding_state": "superharness.engine.onboarding_dao",
        "discussions": "superharness.engine.discussions_dao",
        "inbox": "superharness.engine.inbox_dao",
        "tasks": "superharness.engine.tasks_dao",
        "handoffs": "superharness.engine.handoffs_dao",
        "failures": "superharness.engine.failures_dao",
        "decisions": "superharness.engine.decisions_dao",
        "ledger": "superharness.engine.ledger_dao",
    }
    missing: list[str] = []
    for entry in doc.get("files", []) + doc.get("patterns", []):
        if entry.get("type") != "state":
            continue
        table = entry.get("backed_by")
        if not table:
            continue
        dao_module = table_to_dao.get(table)
        if not dao_module:
            label = entry.get("path") or entry.get("glob")
            missing.append(f"{label} → backed_by={table!r} has no DAO mapping in this guard")
            continue
        try:
            __import__(dao_module)
        except ImportError as e:
            label = entry.get("path") or entry.get("glob")
            missing.append(f"{label} → backed_by={table!r} but DAO import failed: {e}")
    assert not missing, "DAOs missing for state-backed tables:\n  " + "\n  ".join(missing)
