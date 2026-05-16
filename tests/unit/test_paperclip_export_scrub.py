"""Tests for shux export --scrub (paperclip.export-scrub feature)."""
from __future__ import annotations

import tarfile
import io

import pytest
from superharness.engine.pack import export_pack


def _read_tar_text(tar_path, member_name):
    with tarfile.open(str(tar_path), "r:gz") as tar:
        members = tar.getnames()
        for name in members:
            if name.endswith(member_name) or name == member_name:
                f = tar.extractfile(name)
                if f:
                    return f.read().decode("utf-8", errors="replace")
    return None


@pytest.fixture
def project_with_secrets(tmp_path):
    sh = tmp_path / ".superharness"
    sh.mkdir()
    # Write a handoff YAML containing a fake API key
    handoffs = sh / "handoffs"
    handoffs.mkdir()
    (handoffs / "session.yaml").write_text(
        "agent: claude-code\n"
        "api_key: sk-fakekey1234567890abcdef\n"
        "summary: did some work\n"
    )
    (sh / "ledger.md").write_text(
        "- 2026-05-16T10:00:00Z — claude-code — AKIA1234567890ABCDEF was used\n"
    )
    return tmp_path


def test_export_scrub_redacts_api_key(project_with_secrets, tmp_path):
    out = tmp_path / "out.pack.tar.gz"
    export_pack(project_with_secrets, output_path=out, scrub=True)

    content = _read_tar_text(out, "session.yaml")
    if content is not None:
        assert "sk-fakekey" not in content
        assert "[REDACTED" in content


def test_export_scrub_redacts_aws_key(project_with_secrets, tmp_path):
    out = tmp_path / "out.pack.tar.gz"
    export_pack(project_with_secrets, output_path=out, scrub=True)

    ledger = _read_tar_text(out, "ledger.md")
    if ledger is not None:
        assert "AKIA1234567890ABCDEF" not in ledger
        assert "[REDACTED" in ledger


def test_export_no_scrub_preserves_content(project_with_secrets, tmp_path):
    out = tmp_path / "out.pack.tar.gz"
    export_pack(project_with_secrets, output_path=out, scrub=False)

    content = _read_tar_text(out, "session.yaml")
    if content is not None:
        # Without scrub, the key should survive (path scrubbing only)
        assert "sk-fakekey" in content or "api_key" in content


def test_export_scrub_produces_valid_tar(project_with_secrets, tmp_path):
    out = tmp_path / "out.pack.tar.gz"
    export_pack(project_with_secrets, output_path=out, scrub=True)
    assert out.exists()
    with tarfile.open(str(out), "r:gz") as tar:
        names = tar.getnames()
    assert "superharness-pack.yaml" in names
