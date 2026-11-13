"""Publication uploads only package distributions, never the candidate's evidence files.

The candidate draft also carries SHA256SUMS, candidate-manifest.json and an
SBOM. twine rejects any non-distribution file in the upload directory
(``InvalidDistribution: Unknown distribution format: 'SHA256SUMS'``), so each
publish job must stage the wheel and sdist into their own directory and point
the publish action at it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"
PUBLISH_ACTION = "pypa/gh-action-pypi-publish@"
PUBLISH_JOBS = ("publish-testpypi", "publish-pypi")
CANDIDATE_ASSETS = (
    "superharness-1.0.0-py3-none-any.whl",
    "superharness-1.0.0.tar.gz",
    "SHA256SUMS",
    "candidate-manifest.json",
    "sbom.cdx.json",
)


def _steps(job: str) -> list[dict]:
    workflow = yaml.safe_load(PUBLISH_WORKFLOW.read_text())
    return workflow["jobs"][job]["steps"]


def _publish_step_index(steps: list[dict]) -> int:
    for index, step in enumerate(steps):
        if str(step.get("uses", "")).startswith(PUBLISH_ACTION):
            return index
    raise AssertionError("publish job has no pypa/gh-action-pypi-publish step")


@pytest.mark.parametrize("job", PUBLISH_JOBS)
def test_publish_action_reads_a_directory_other_than_dist(job: str) -> None:
    steps = _steps(job)
    publish = steps[_publish_step_index(steps)]
    packages_dir = (publish.get("with") or {}).get("packages-dir", "dist/")

    assert packages_dir.rstrip("/") != "dist"


@pytest.mark.parametrize("job", PUBLISH_JOBS)
def test_staging_step_copies_only_wheel_and_sdist(job: str, tmp_path: Path) -> None:
    steps = _steps(job)
    publish_index = _publish_step_index(steps)
    packages_dir = steps[publish_index]["with"]["packages-dir"].rstrip("/")
    staging = [
        step
        for step in steps[:publish_index]
        if packages_dir in str(step.get("run", ""))
    ]
    assert staging, f"no step before the publish action stages {packages_dir}/"

    dist = tmp_path / "dist"
    dist.mkdir()
    for name in CANDIDATE_ASSETS:
        (dist / name).write_text(name)
    for step in staging:
        subprocess.run(
            ["bash", "-euo", "pipefail", "-c", step["run"]], cwd=tmp_path, check=True
        )

    staged = sorted(path.name for path in (tmp_path / packages_dir).iterdir())
    assert staged == sorted(CANDIDATE_ASSETS[:2])
