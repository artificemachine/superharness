"""Workflows that gate pull requests also run in the GitHub merge queue."""

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))


def _triggers(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    # PyYAML reads the bare key `on` as the boolean True.
    triggers = data.get(True, data.get("on")) or {}
    if isinstance(triggers, str):
        return {triggers: None}
    if isinstance(triggers, list):
        return dict.fromkeys(triggers)
    return triggers


PR_WORKFLOWS = [p for p in WORKFLOWS if "pull_request" in _triggers(p)]


def test_pull_request_workflows_exist() -> None:
    assert PR_WORKFLOWS, "no workflow runs on pull_request; the glob is wrong"


@pytest.mark.parametrize("path", PR_WORKFLOWS, ids=lambda p: p.name)
def test_pull_request_workflow_also_runs_in_merge_queue(path: Path) -> None:
    # Without merge_group the queue waits forever for the required checks.
    assert "merge_group" in _triggers(path), f"{path.name} runs on pull_request but not merge_group"


@pytest.mark.parametrize("path", PR_WORKFLOWS, ids=lambda p: p.name)
def test_pull_request_base_sha_has_merge_group_fallback(path: Path) -> None:
    # A step diffing against the PR base must diff against the queue base too,
    # or it silently skips or scans the wrong range inside the queue.
    text = path.read_text()
    if "github.event.pull_request.base.sha" in text:
        assert "github.event.merge_group.base_sha" in text, (
            f"{path.name} reads the pull_request base sha without a merge_group fallback"
        )
