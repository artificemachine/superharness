"""Release-candidate manifest, checksums, and promotion gate.

The candidate workflow builds ``dist/`` exactly once, records every
artifact's SHA-256 in an immutable ``candidate-manifest.json`` and a
standard ``SHA256SUMS`` file bound to the full 40-character commit SHA,
and publishes both (plus a generated SBOM) as assets of a GitHub *draft*
release named ``candidate-<full-commit-sha>``. Promotion jobs (tag/release,
TestPyPI, PyPI) may only consume that draft via its numeric release ID and
must recompute every checksum against the files they actually upload.

Stdlib only — this module runs as a step in GitHub Actions jobs on bare
``ubuntu-latest`` Python 3.11+, both via ``python3 -m`` and as a plain
script (``python3 src/superharness/release_candidate.py ...``), before any
package install has happened. It mirrors the discipline of
``scripts/release_preflight.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
MANIFEST_NAME = "candidate-manifest.json"
SUMS_NAME = "SHA256SUMS"
SBOM_NAME = "candidate-sbom.json"
_DIST_ARTIFACT_RE = re.compile(r".*\.(whl|tar\.gz)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FULL_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class CandidateManifestError(Exception):
    """Raised when a candidate manifest, its checksums, or its promotion is invalid."""


# ---------------------------------------------------------------------------
# Manifest construction and validation
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dist_artifacts(dist_dir: Path) -> list[Path]:
    """Every wheel/sdist file in ``dist_dir``, sorted for stable ordering."""
    return sorted(p for p in dist_dir.iterdir() if p.is_file() and _DIST_ARTIFACT_RE.match(p.name))


def build_manifest(dist_dir: Path, commit_sha: str, version: str) -> dict:
    """Build the candidate manifest for the artifacts in ``dist_dir``.

    Raises ``CandidateManifestError`` on an abbreviated commit SHA, a
    missing version, or an empty dist directory.
    """
    commit_sha = (commit_sha or "").strip().lower()
    if not _FULL_COMMIT_RE.match(commit_sha):
        raise CandidateManifestError(
            f"commit_sha {commit_sha!r} is not a full 40-character git commit SHA "
            "(abbreviated identities are not allowed in a candidate manifest)"
        )
    version = (version or "").strip()
    if not version:
        raise CandidateManifestError("candidate manifest requires a non-empty version")
    if not dist_dir.is_dir():
        raise CandidateManifestError(f"dist directory {dist_dir} does not exist")

    artifacts = []
    for path in dist_artifacts(dist_dir):
        artifacts.append(
            {
                "filename": path.name,
                "sha256": _sha256_file(path),
                "size": path.stat().st_size,
            }
        )
    if not artifacts:
        raise CandidateManifestError(f"no wheel/sdist artifacts found in {dist_dir}")

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "release-candidate-manifest",
        "commit": commit_sha,
        "version": version,
        "artifacts": artifacts,
    }


def validate_manifest(manifest: dict) -> dict:
    """Validate an already-built manifest; returns it unchanged on success.

    Raises ``CandidateManifestError`` on any structural problem: wrong kind,
    abbreviated commit, missing version, or malformed artifact entries.
    """
    if not isinstance(manifest, dict):
        raise CandidateManifestError("candidate manifest must be a JSON object")
    if manifest.get("kind") != "release-candidate-manifest":
        raise CandidateManifestError("not a release-candidate-manifest (missing/invalid 'kind')")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise CandidateManifestError(f"unsupported schema_version: {manifest.get('schema_version')!r}")

    commit = (manifest.get("commit") or "").strip().lower()
    if not _FULL_COMMIT_RE.match(commit):
        raise CandidateManifestError(
            f"candidate manifest commit {manifest.get('commit')!r} is not a full "
            "40-character git commit SHA"
        )
    version = (manifest.get("version") or "").strip()
    if not version:
        raise CandidateManifestError("candidate manifest requires a non-empty version")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise CandidateManifestError("candidate manifest requires a non-empty artifacts list")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise CandidateManifestError("artifact entries must be JSON objects")
        filename = artifact.get("filename")
        sha256 = artifact.get("sha256")
        if not isinstance(filename, str) or not filename:
            raise CandidateManifestError("artifact entry missing 'filename'")
        if not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
            raise CandidateManifestError(
                f"artifact {filename!r} has invalid sha256 {sha256!r}"
            )

    return manifest


def load_manifest(path: Path) -> dict:
    """Load and validate a manifest JSON file from disk."""
    try:
        manifest = json.loads(path.read_text())
    except OSError as exc:
        raise CandidateManifestError(f"could not read manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CandidateManifestError(f"manifest {path} is not valid JSON: {exc}") from exc
    return validate_manifest(manifest)


# ---------------------------------------------------------------------------
# Checksum bundle writing and verification
# ---------------------------------------------------------------------------


def write_candidate_files(dist_dir: Path, manifest: dict) -> None:
    """Write ``candidate-manifest.json`` and ``SHA256SUMS`` beside the dist artifacts."""
    validate_manifest(manifest)
    (dist_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    lines = [f"{a['sha256']}  {a['filename']}" for a in manifest["artifacts"]]
    (dist_dir / SUMS_NAME).write_text("\n".join(lines) + "\n")


def verify_dist_against_manifest(dist_dir: Path, manifest: dict) -> None:
    """Recompute every dist artifact hash and compare with the manifest.

    Raises ``CandidateManifestError`` on any SHA-256 mismatch, missing file,
    or artifact present on disk but absent from the manifest.
    """
    validate_manifest(manifest)
    recorded = {a["filename"]: a["sha256"] for a in manifest["artifacts"]}
    on_disk = {p.name for p in dist_artifacts(dist_dir)}

    for missing in sorted(set(recorded) - on_disk):
        raise CandidateManifestError(f"artifact {missing!r} recorded in manifest but missing from dist")
    for extra in sorted(on_disk - set(recorded)):
        raise CandidateManifestError(f"artifact {extra!r} on disk but not recorded in manifest")

    for filename, expected in sorted(recorded.items()):
        actual = _sha256_file(dist_dir / filename)
        if actual != expected:
            raise CandidateManifestError(
                f"SHA-256 mismatch for {filename!r}: manifest records {expected}, "
                f"dist file computes {actual}"
            )


def verify_sha256sums(dist_dir: Path, sums_path: Path | None = None) -> None:
    """Recompute every ``SHA256SUMS`` line against the files in ``dist_dir``.

    Raises ``CandidateManifestError`` on malformed lines, hash mismatches, or
    wheel/sdist files not covered by the sums file.
    """
    sums_path = sums_path or dist_dir / SUMS_NAME
    try:
        text = sums_path.read_text()
    except OSError as exc:
        raise CandidateManifestError(f"could not read {sums_path}: {exc}") from exc

    recorded: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or not _SHA256_RE.match(parts[0]) or not parts[1].strip():
            raise CandidateManifestError(f"malformed SHA256SUMS line {lineno}: {line!r}")
        recorded[parts[1].strip()] = parts[0]

    if not recorded:
        raise CandidateManifestError("SHA256SUMS file is empty")

    on_disk = {p.name for p in dist_artifacts(dist_dir)}
    for missing in sorted(set(recorded) - on_disk):
        raise CandidateManifestError(f"SHA256SUMS records {missing!r} but it is missing from dist")
    for extra in sorted(on_disk - set(recorded)):
        raise CandidateManifestError(f"SHA256SUMS missing entry for dist file {extra!r}")

    for filename, expected in sorted(recorded.items()):
        actual = _sha256_file(dist_dir / filename)
        if actual != expected:
            raise CandidateManifestError(
                f"SHA256SUMS mismatch for {filename!r}: recorded {expected}, file computes {actual}"
            )


# ---------------------------------------------------------------------------
# SBOM
# ---------------------------------------------------------------------------


def build_sbom(dist_dir: Path, manifest: dict) -> dict:
    """Build a minimal CycloneDX 1.5 JSON SBOM covering every dist artifact."""
    validate_manifest(manifest)
    components = []
    for artifact in manifest["artifacts"]:
        components.append(
            {
                "type": "file",
                "name": artifact["filename"],
                "version": manifest["version"],
                "hashes": [{"alg": "SHA-256", "content": artifact["sha256"]}],
            }
        )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "superharness",
                "version": manifest["version"],
            },
            "properties": [
                {"name": "superharness:candidate:commit", "value": manifest["commit"]},
            ],
        },
        "components": components,
    }


# ---------------------------------------------------------------------------
# Promotion gate
# ---------------------------------------------------------------------------


def check_promotion(manifest: dict, approval: dict | None) -> dict:
    """Gate promotion (tag/release, TestPyPI, PyPI) on explicit approval.

    ``approval`` is the operator-supplied evidence, e.g.
    ``{"approved": true, "approver": "max", "candidate_release_id": "123"}``.
    Returns ``{"commit", "version", "candidate_release_id"}`` on success.
    Raises ``CandidateManifestError`` when the manifest is invalid or the
    approval evidence is missing/incomplete — a candidate can never promote
    itself.
    """
    validate_manifest(manifest)

    if not isinstance(approval, dict):
        raise CandidateManifestError(
            "promotion rejected: no approval evidence supplied — a candidate "
            "must be explicitly approved before tag/release or publish"
        )
    if approval.get("approved") is not True:
        raise CandidateManifestError("promotion rejected: approval evidence is not granted")
    approver = (approval.get("approver") or "").strip()
    if not approver:
        raise CandidateManifestError("promotion rejected: approval evidence lacks an approver")
    candidate_release_id = str(approval.get("candidate_release_id") or "").strip()
    if not candidate_release_id.isdigit():
        raise CandidateManifestError(
            "promotion rejected: approval evidence lacks a numeric candidate_release_id"
        )

    return {
        "commit": manifest["commit"],
        "version": manifest["version"],
        "candidate_release_id": candidate_release_id,
    }


# ---------------------------------------------------------------------------
# CLI (used by the GitHub Actions workflows)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="release_candidate",
        description=(
            "Build, verify, or gate a release-candidate manifest for dist/ "
            "artifacts. Stdlib only; safe to run on bare CI runners."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--dist", required=True, type=Path, help="Path to the dist/ directory")

    p_build = sub.add_parser("build", help="Build manifest, SHA256SUMS, and SBOM in dist/")
    _add_common(p_build)
    p_build.add_argument("--commit", required=True, help="Full 40-character commit SHA")
    p_build.add_argument("--version", required=True, help="Package version, e.g. 1.84.1")

    p_verify = sub.add_parser("verify", help="Verify dist files against manifest and SHA256SUMS")
    _add_common(p_verify)
    p_verify.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=f"Manifest path (default: <dist>/{MANIFEST_NAME})",
    )

    p_promote = sub.add_parser("promote", help="Validate the manifest plus approval evidence")
    p_promote.add_argument("--manifest", required=True, type=Path, help="Path to candidate-manifest.json")
    p_promote.add_argument("--approver", required=True, help="Who approved promotion")
    p_promote.add_argument(
        "--candidate-release-id", required=True, help="Numeric GitHub release ID of the candidate draft"
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            manifest = build_manifest(args.dist, commit_sha=args.commit, version=args.version)
            write_candidate_files(args.dist, manifest)
            sbom_path = args.dist / SBOM_NAME
            sbom_path.write_text(json.dumps(build_sbom(args.dist, manifest), indent=2) + "\n")
            print(json.dumps({"manifest": str(args.dist / MANIFEST_NAME), "sbom": str(sbom_path)}))
        elif args.command == "verify":
            manifest = load_manifest(args.manifest or args.dist / MANIFEST_NAME)
            verify_dist_against_manifest(args.dist, manifest)
            if (args.dist / SUMS_NAME).exists():
                verify_sha256sums(args.dist)
            print(json.dumps({"commit": manifest["commit"], "version": manifest["version"]}))
        elif args.command == "promote":
            manifest = load_manifest(args.manifest)
            promoted = check_promotion(
                manifest,
                {
                    "approved": True,
                    "approver": args.approver,
                    "candidate_release_id": args.candidate_release_id,
                },
            )
            print(json.dumps(promoted))
    except CandidateManifestError as exc:
        print(f"release candidate error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
