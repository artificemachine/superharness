"""Publication workflow permissions stay scoped to candidate retrieval."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish.yml"


def test_candidate_fetch_job_can_read_release_candidate() -> None:
    workflow = yaml.safe_load(PUBLISH_WORKFLOW.read_text())
    permissions = workflow["jobs"]["fetch-candidate"].get("permissions", {})

    assert permissions.get("contents") == "write"
