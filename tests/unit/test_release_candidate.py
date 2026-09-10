"""Iteration 2 of the release-candidate rollout plan — checksumed candidate.

A release candidate is an immutable bundle: the exact files built into
``dist/`` once, their SHA-256 hashes recorded in ``candidate-manifest.json``
and ``SHA256SUMS``, bound to the full 40-character commit SHA that produced
them. Tag/release and TestPyPI/PyPI promotion may only consume a candidate
whose recorded hashes still match the files being uploaded, and only after
explicit approval evidence exists. This guards the failure class where a
rebuilt or mutated artifact is published under a version whose hash nobody
verified.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from superharness.release_candidate import (
    CandidateManifestError,
    build_manifest,
    build_sbom,
    check_promotion,
    load_manifest,
    validate_manifest,
    verify_dist_against_manifest,
    verify_sha256sums,
    write_candidate_files,
)

FULL_COMMIT = "a" * 40
FULL_COMMIT_2 = "b" * 40


def _fake_dist(dist_dir: Path) -> dict[str, bytes]:
    """Create wheel/sdist stand-ins with fixed contents and return them."""
    payloads = {
        "superharness-1.84.1-py3-none-any.whl": b"wheel-bytes-1.84.1",
        "superharness-1.84.1.tar.gz": b"sdist-bytes-1.84.1",
    }
    dist_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (dist_dir / name).write_bytes(payload)
    return payloads


def test_candidate_manifest_matches_dist_hashes(tmp_path: Path) -> None:
    """Every wheel/sdist entry equals its SHA-256, on disk and in SHA256SUMS."""
    dist_dir = tmp_path / "dist"
    payloads = _fake_dist(dist_dir)

    manifest = build_manifest(dist_dir, commit_sha=FULL_COMMIT, version="1.84.1")
    validate_manifest(manifest)

    by_name = {a["filename"]: a for a in manifest["artifacts"]}
    assert set(by_name) == set(payloads)
    for name, payload in payloads.items():
        assert by_name[name]["sha256"] == hashlib.sha256(payload).hexdigest()
        assert by_name[name]["size"] == len(payload)
    assert manifest["commit"] == FULL_COMMIT
    assert manifest["version"] == "1.84.1"

    write_candidate_files(dist_dir, manifest)
    saved = load_manifest(dist_dir / "candidate-manifest.json")
    assert saved == manifest

    # The written SHA256SUMS must match the files on disk verbatim.
    verify_sha256sums(dist_dir)
    verify_dist_against_manifest(dist_dir, saved)


def test_candidate_manifest_rejects_tag_before_approval(tmp_path: Path) -> None:
    """Promotion to tag/release is rejected until approval evidence exists."""
    dist_dir = tmp_path / "dist"
    _fake_dist(dist_dir)
    manifest = build_manifest(dist_dir, commit_sha=FULL_COMMIT, version="1.84.1")

    with pytest.raises(CandidateManifestError, match="approval"):
        check_promotion(manifest, None)

    with pytest.raises(CandidateManifestError, match="approval"):
        check_promotion(manifest, {"approved": False, "approver": "max", "candidate_release_id": "123"})

    with pytest.raises(CandidateManifestError, match="approval"):
        check_promotion(manifest, {"approved": True, "approver": "", "candidate_release_id": "123"})

    with pytest.raises(CandidateManifestError, match="approval"):
        check_promotion(manifest, {"approved": True, "approver": "max", "candidate_release_id": ""})

    promoted = check_promotion(
        manifest, {"approved": True, "approver": "max", "candidate_release_id": "123"}
    )
    assert promoted == {
        "commit": FULL_COMMIT,
        "version": "1.84.1",
        "candidate_release_id": "123",
    }


def test_candidate_manifest_requires_full_commit_and_version(tmp_path: Path) -> None:
    """Abbreviated commit SHAs and missing versions must be refused."""
    dist_dir = tmp_path / "dist"
    _fake_dist(dist_dir)

    with pytest.raises(CandidateManifestError, match="40"):
        build_manifest(dist_dir, commit_sha="abc1234", version="1.84.1")

    with pytest.raises(CandidateManifestError, match="version"):
        build_manifest(dist_dir, commit_sha=FULL_COMMIT, version="")

    with pytest.raises(CandidateManifestError, match="version"):
        build_manifest(dist_dir, commit_sha=FULL_COMMIT, version="   ")

    manifest = build_manifest(dist_dir, commit_sha=FULL_COMMIT, version="1.84.1")
    abbreviated = dict(manifest, commit=FULL_COMMIT[:7])
    with pytest.raises(CandidateManifestError, match="40"):
        validate_manifest(abbreviated)

    with pytest.raises(CandidateManifestError, match="version"):
        validate_manifest(dict(manifest, version=""))


def test_hash_mismatch_between_dist_file_and_manifest(tmp_path: Path) -> None:
    """A dist file mutated after manifest creation must fail verification."""
    dist_dir = tmp_path / "dist"
    _fake_dist(dist_dir)
    manifest = build_manifest(dist_dir, commit_sha=FULL_COMMIT, version="1.84.1")

    wheel = dist_dir / "superharness-1.84.1-py3-none-any.whl"
    wheel.write_bytes(b"TAMPERED-PAYLOAD")

    with pytest.raises(CandidateManifestError, match="SHA-256 mismatch"):
        verify_dist_against_manifest(dist_dir, manifest)


def test_hash_mismatch_between_sha256sums_and_files(tmp_path: Path) -> None:
    """A tampered SHA256SUMS line must fail verification."""
    dist_dir = tmp_path / "dist"
    payloads = _fake_dist(dist_dir)
    manifest = build_manifest(dist_dir, commit_sha=FULL_COMMIT, version="1.84.1")
    write_candidate_files(dist_dir, manifest)

    sums_path = dist_dir / "SHA256SUMS"
    good_hash = hashlib.sha256(payloads["superharness-1.84.1.tar.gz"]).hexdigest()
    bad_hash = ("0" if good_hash[0] != "0" else "1") + good_hash[1:]
    original = sums_path.read_text()
    tampered = original.replace(good_hash, bad_hash)
    assert tampered != original
    sums_path.write_text(tampered)

    with pytest.raises(CandidateManifestError, match="SHA256SUMS"):
        verify_sha256sums(dist_dir)


def test_sbom_records_every_dist_artifact(tmp_path: Path) -> None:
    """The generated SBOM names every dist artifact with its hash."""
    dist_dir = tmp_path / "dist"
    payloads = _fake_dist(dist_dir)
    manifest = build_manifest(dist_dir, commit_sha=FULL_COMMIT, version="1.84.1")

    sbom = build_sbom(dist_dir, manifest)
    assert json.dumps(sbom)  # JSON-serializable
    names = {c["name"] for c in sbom["components"]}
    assert names == set(payloads)
    for component in sbom["components"]:
        hashes = {h["alg"]: h["content"] for h in component["hashes"]}
        assert hashes["SHA-256"] == hashlib.sha256(payloads[component["name"]]).hexdigest()
