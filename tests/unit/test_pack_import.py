"""Tests for superharness pack import engine."""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pack(tmp_path: Path, manifest_override: dict | None = None, extra_files: dict | None = None) -> Path:
    """Build a minimal valid pack tarball and return its path."""
    pack_path = tmp_path / "test.superharness.pack.tar.gz"

    manifest = {
        "format_version": "1",
        "created_at": "2026-01-01T00:00:00Z",
        "source_project": "test-project",
    }
    if manifest_override:
        manifest.update(manifest_override)

    manifest_bytes = yaml.dump(manifest).encode()

    files = {
        ".superharness/contract.yaml": b"project_path: .\ntasks: []\n",
        ".superharness/ledger.md": b"# Ledger\n",
        ".superharness/handoffs/handoff-01.yaml": b"id: handoff-01\n",
    }
    if extra_files:
        files.update(extra_files)

    with tarfile.open(str(pack_path), "w:gz") as tar:
        info = tarfile.TarInfo(name="superharness-pack.yaml")
        info.size = len(manifest_bytes)
        tar.addfile(info, io.BytesIO(manifest_bytes))

        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    return pack_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_import_extracts_files(tmp_path):
    from superharness.engine.pack import import_pack

    pack = _make_pack(tmp_path)
    dest = tmp_path / "dest"
    dest.mkdir()

    result = import_pack(pack, dest)

    assert (dest / ".superharness" / "contract.yaml").exists()
    assert (dest / ".superharness" / "ledger.md").exists()
    assert len(result["imported"]) > 0


def test_import_skip_collision(tmp_path):
    from superharness.engine.pack import import_pack

    pack = _make_pack(tmp_path)
    dest = tmp_path / "dest"
    dest.mkdir()
    sh = dest / ".superharness"
    sh.mkdir()
    existing = sh / "contract.yaml"
    original_content = b"project_path: /original\ntasks: []\n"
    existing.write_bytes(original_content)

    result = import_pack(pack, dest, collision="skip")

    # Existing file should be unchanged
    assert existing.read_bytes() == original_content
    assert ".superharness/contract.yaml" in result["skipped"]


def test_import_overwrite_collision(tmp_path):
    from superharness.engine.pack import import_pack

    pack = _make_pack(tmp_path)
    dest = tmp_path / "dest"
    dest.mkdir()
    sh = dest / ".superharness"
    sh.mkdir()
    existing = sh / "contract.yaml"
    existing.write_bytes(b"project_path: /original\ntasks: []\n")

    result = import_pack(pack, dest, collision="overwrite")

    # File should be replaced with pack version
    assert existing.read_bytes() == b"project_path: .\ntasks: []\n"
    assert ".superharness/contract.yaml" in result["imported"]


def test_import_fail_collision(tmp_path):
    from superharness.engine.pack import import_pack

    pack = _make_pack(tmp_path)
    dest = tmp_path / "dest"
    dest.mkdir()
    sh = dest / ".superharness"
    sh.mkdir()
    (sh / "contract.yaml").write_bytes(b"project_path: /original\n")

    with pytest.raises(RuntimeError, match="collision"):
        import_pack(pack, dest, collision="fail")


def test_import_validates_manifest(tmp_path):
    from superharness.engine.pack import import_pack

    # Build a pack WITHOUT the manifest
    pack_path = tmp_path / "bad.tar.gz"
    with tarfile.open(str(pack_path), "w:gz") as tar:
        data = b"project_path: .\n"
        info = tarfile.TarInfo(name=".superharness/contract.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(ValueError, match="manifest"):
        import_pack(pack_path, dest)


def test_import_validates_format_version(tmp_path):
    from superharness.engine.pack import import_pack

    pack = _make_pack(tmp_path, manifest_override={"format_version": "99"})
    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(ValueError, match="format version"):
        import_pack(pack, dest)


def test_import_creates_superharness_dir(tmp_path):
    from superharness.engine.pack import import_pack

    pack = _make_pack(tmp_path)
    dest = tmp_path / "dest"
    dest.mkdir()

    # .superharness does NOT exist yet
    assert not (dest / ".superharness").exists()

    import_pack(pack, dest)

    assert (dest / ".superharness").exists()
    assert (dest / ".superharness" / "contract.yaml").exists()


def test_roundtrip_preserves_contract_tasks(tmp_path):
    """Export then import: task IDs in contract should be preserved."""
    from superharness.engine.pack import export_pack, import_pack

    # Build source project
    src = tmp_path / "src"
    sh = src / ".superharness"
    sh.mkdir(parents=True)

    contract = {
        "project_path": "/home/testuser/src",
        "tasks": [
            {"id": "task-001", "title": "Alpha", "status": "open", "owner": "claude-code", "project_path": "/home/testuser/src"},
            {"id": "task-002", "title": "Beta",  "status": "done", "owner": "codex-cli",   "project_path": "/home/testuser/src"},
        ],
    }
    (sh / "contract.yaml").write_text(yaml.dump(contract))
    (sh / "ledger.md").write_text("# Ledger\n")

    # Export
    pack = export_pack(src, output_path=tmp_path / "round.tar.gz")

    # Import into fresh destination
    dest = tmp_path / "dest"
    dest.mkdir()
    import_pack(pack, dest)

    result_contract = yaml.safe_load((dest / ".superharness" / "contract.yaml").read_text())
    ids = {t["id"] for t in result_contract["tasks"]}
    assert ids == {"task-001", "task-002"}


def test_import_missing_pack_file_raises(tmp_path):
    from superharness.engine.pack import import_pack

    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(FileNotFoundError):
        import_pack(tmp_path / "nonexistent.tar.gz", dest)
