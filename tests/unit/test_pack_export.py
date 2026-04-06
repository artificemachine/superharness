"""Tests for superharness pack export engine."""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def project_dir(tmp_path):
    """Minimal fake project with .superharness/ directory."""
    sh = tmp_path / ".superharness"
    sh.mkdir()

    # contract.yaml with absolute paths
    contract = {
        "project_path": "/home/testuser/projects/myapp",
        "tasks": [
            {
                "id": "t1",
                "title": "Fix bug in /home/testuser/projects/myapp/src/foo.py",
                "owner": "claude-code",
                "status": "open",
                "project_path": "/home/testuser/projects/myapp",
                "summary": "See /home/testuser/projects/myapp/README.md",
            }
        ],
    }
    (sh / "contract.yaml").write_text(yaml.dump(contract))

    # inbox.yaml with absolute path
    inbox_content = {"items": [{"id": "i1", "path": "/home/testuser/projects/myapp/task.yaml"}]}
    (sh / "inbox.yaml").write_text(yaml.dump(inbox_content))

    # ledger.md
    (sh / "ledger.md").write_text("# Ledger\n\n- Task t1 closed\n")

    # handoffs/
    handoffs = sh / "handoffs"
    handoffs.mkdir()
    (handoffs / "handoff-01.yaml").write_text("id: handoff-01\nsummary: first handoff\n")

    # decisions.yaml
    (sh / "decisions.yaml").write_text("decisions: []\n")

    # Machine-local files that should be excluded
    (sh / "watcher.yaml").write_text("interval: 30\n")
    (sh / "watcher.heartbeat.yaml").write_text("last_beat: 2026-01-01\n")
    (sh / "watcher-env.yaml").write_text("user: alice\n")
    (sh / "monitor-health.log").write_text("ok\n")
    (sh / "inbox.archive.yaml").write_text("archived: []\n")

    launcher_logs = sh / "launcher-logs"
    launcher_logs.mkdir()
    (launcher_logs / "run-01.log").write_text("started\n")

    agents_dir = sh / "agents"
    agents_dir.mkdir()
    (agents_dir / "agent-state.yaml").write_text("state: idle\n")

    (sh / "heartbeat.yaml").write_text("pulse: ok\n")

    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_export_creates_tarball(project_dir, tmp_path):
    from superharness.engine.pack import export_pack

    output = tmp_path / "out.tar.gz"
    result = export_pack(project_dir, output_path=output)

    assert result == output
    assert output.exists()
    assert output.stat().st_size > 0


def test_export_contains_manifest(project_dir, tmp_path):
    from superharness.engine.pack import export_pack

    output = tmp_path / "out.tar.gz"
    export_pack(project_dir, output_path=output)

    with tarfile.open(str(output), "r:gz") as tar:
        names = tar.getnames()

    assert "superharness-pack.yaml" in names

    with tarfile.open(str(output), "r:gz") as tar:
        f = tar.extractfile("superharness-pack.yaml")
        manifest = yaml.safe_load(f.read().decode())

    assert manifest["format_version"] == "1"
    assert "created_at" in manifest
    assert "source_project" in manifest


def test_export_scrubs_absolute_paths_in_contract(project_dir, tmp_path):
    from superharness.engine.pack import export_pack

    output = tmp_path / "out.tar.gz"
    export_pack(project_dir, output_path=output)

    with tarfile.open(str(output), "r:gz") as tar:
        f = tar.extractfile(".superharness/contract.yaml")
        doc = yaml.safe_load(f.read().decode())

    assert doc["project_path"] == "."
    assert doc["tasks"][0]["project_path"] == "."


def test_export_scrubs_absolute_paths_in_yaml(project_dir, tmp_path):
    from superharness.engine.pack import export_pack

    output = tmp_path / "out.tar.gz"
    export_pack(project_dir, output_path=output)

    with tarfile.open(str(output), "r:gz") as tar:
        f = tar.extractfile(".superharness/inbox.yaml")
        doc = yaml.safe_load(f.read().decode())

    # /home/testuser/... path should be replaced with "."
    path_val = doc["items"][0]["path"]
    assert "/home/testuser/" not in path_val
    assert path_val == "."


def test_export_excludes_machine_local_files(project_dir, tmp_path):
    from superharness.engine.pack import export_pack

    output = tmp_path / "out.tar.gz"
    export_pack(project_dir, output_path=output)

    with tarfile.open(str(output), "r:gz") as tar:
        names = tar.getnames()

    assert ".superharness/watcher.yaml" not in names
    assert ".superharness/watcher-env.yaml" not in names
    assert ".superharness/monitor-health.log" not in names
    assert ".superharness/inbox.archive.yaml" not in names
    assert ".superharness/heartbeat.yaml" not in names


def test_export_excludes_watcher_heartbeat(project_dir, tmp_path):
    from superharness.engine.pack import export_pack

    output = tmp_path / "out.tar.gz"
    export_pack(project_dir, output_path=output)

    with tarfile.open(str(output), "r:gz") as tar:
        names = tar.getnames()

    assert ".superharness/watcher.heartbeat.yaml" not in names


def test_export_excludes_launcher_logs(project_dir, tmp_path):
    from superharness.engine.pack import export_pack

    output = tmp_path / "out.tar.gz"
    export_pack(project_dir, output_path=output)

    with tarfile.open(str(output), "r:gz") as tar:
        names = tar.getnames()

    assert not any("launcher-logs" in n for n in names)


def test_export_includes_portable_files(project_dir, tmp_path):
    from superharness.engine.pack import export_pack

    output = tmp_path / "out.tar.gz"
    export_pack(project_dir, output_path=output)

    with tarfile.open(str(output), "r:gz") as tar:
        names = tar.getnames()

    assert ".superharness/contract.yaml" in names
    assert ".superharness/inbox.yaml" in names
    assert ".superharness/ledger.md" in names
    assert ".superharness/decisions.yaml" in names
    assert any("handoffs" in n for n in names)


def test_export_missing_superharness_dir_raises(tmp_path):
    from superharness.engine.pack import export_pack

    empty_dir = tmp_path / "no-superharness"
    empty_dir.mkdir()

    with pytest.raises(FileNotFoundError, match=r"\.superharness"):
        export_pack(empty_dir)


def test_export_default_output_path_naming(project_dir, tmp_path):
    """Default output filename follows <project>-<timestamp>.superharness.pack.tar.gz."""
    import os
    from superharness.engine.pack import export_pack

    orig_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = export_pack(project_dir)
        assert result.name.endswith(".superharness.pack.tar.gz")
        assert project_dir.name in result.name
        result.unlink()
    finally:
        os.chdir(orig_cwd)
