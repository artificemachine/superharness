import subprocess
from pathlib import Path

import pytest
import yaml

from superharness.ci_merge_group_reuse import (
    REQUIRED_JOBS,
    complete_jobs,
    has_reusable_evidence,
    lookup_evidence,
    reusable_run,
)


@pytest.mark.parametrize(
    "event,sha,status,conclusion,expected",
    [
        ("merge_group", "a" * 40, "completed", "success", True),
        ("push", "a" * 40, "completed", "success", False),
        ("merge_group", "b" * 40, "completed", "success", False),
        ("merge_group", "a" * 40, "in_progress", None, False),
        ("merge_group", "a" * 40, "completed", "failure", False),
    ],
)
def test_reuse_requires_successful_merge_group_on_exact_sha(
    event, sha, status, conclusion, expected
):
    run = {"event": event, "head_sha": sha, "status": status, "conclusion": conclusion}
    assert reusable_run(run, "a" * 40) is expected


def test_all_test_layers_must_have_succeeded():
    jobs = [
        {"name": name, "conclusion": "success", "status": "completed"}
        for name in REQUIRED_JOBS
    ]
    assert complete_jobs(jobs)
    assert not complete_jobs(jobs[:-1])
    assert not complete_jobs(
        jobs
        + [{"name": jobs[0]["name"], "conclusion": "failure", "status": "completed"}]
    )
    jobs[0]["conclusion"] = "skipped"
    assert not complete_jobs(jobs)


def test_reuse_requires_latest_run_and_complete_job_evidence():
    sha = "a" * 40
    run = {
        "id": 42,
        "event": "merge_group",
        "head_sha": sha,
        "status": "completed",
        "conclusion": "success",
    }
    jobs = [
        {"name": name, "conclusion": "success", "status": "completed"}
        for name in REQUIRED_JOBS
    ]
    assert has_reusable_evidence([run], jobs, sha)
    assert not has_reusable_evidence([], jobs, sha)
    assert not has_reusable_evidence([run, run], jobs, sha)
    assert not has_reusable_evidence([run], jobs[:-1], sha)
    assert not has_reusable_evidence([{**run, "status": "in_progress"}], jobs, sha)


def test_lookup_falls_back_if_api_fails_or_event_is_not_main_push():
    def unavailable(_path):
        raise OSError("unavailable")

    assert not lookup_evidence("push", "a" * 40, unavailable)
    assert not lookup_evidence("pull_request", "a" * 40, unavailable)


def test_lookup_accepts_only_complete_jobs_for_exact_sha():
    sha = "a" * 40
    run = {
        "id": 42,
        "event": "merge_group",
        "head_sha": sha,
        "status": "completed",
        "conclusion": "success",
    }
    jobs = [
        {"name": name, "conclusion": "success", "status": "completed"}
        for name in REQUIRED_JOBS
    ]

    def api(path):
        if "/workflows/" in path:
            return {"total_count": 1, "workflow_runs": [run]}
        return {"total_count": len(jobs), "jobs": jobs}

    assert lookup_evidence("push", sha, api)


def test_workflow_falls_back_to_tests_without_verified_reuse():
    workflow = yaml.safe_load(
        (
            Path(__file__).resolve().parents[2] / ".github/workflows/tests.yml"
        ).read_text()
    )
    jobs = workflow["jobs"]
    assert jobs["changes"]["outputs"]["reuse"] == "${{ steps.reuse.outputs.reuse }}"
    for job in (
        "smoke-tests",
        "unit-tests",
        "integration-tests",
        "e2e-tests",
        "other-tests",
    ):
        assert "needs.changes.outputs.reuse != 'true'" in jobs[job]["if"]
    assert "REUSE" in jobs["qa-gate"]["steps"][0]["env"]


@pytest.mark.parametrize(
    "reuse,shell,unit,expected",
    [
        ("true", "success", "skipped", 0),
        ("true", "failure", "skipped", 1),
        ("false", "success", "skipped", 1),
        ("false", "success", "success", 0),
    ],
)
def test_qa_gate_enforces_reuse_and_fallback(reuse, shell, unit, expected):
    workflow = yaml.safe_load(
        (
            Path(__file__).resolve().parents[2] / ".github/workflows/tests.yml"
        ).read_text()
    )
    script = workflow["jobs"]["qa-gate"]["steps"][0]["run"]
    env = {
        "CHANGES_RESULT": "success",
        "DOCS_ONLY": "false",
        "REUSE": reuse,
        "SHELL_TESTS": shell,
        "SMOKE_TESTS": "skipped" if reuse == "true" else "success",
        "UNIT_TESTS": unit,
        "INTEGRATION_TESTS": "skipped" if reuse == "true" else "success",
        "E2E_TESTS": "skipped" if reuse == "true" else "success",
        "OTHER_TESTS": "skipped" if reuse == "true" else "success",
    }
    assert (
        subprocess.run(
            ["bash", "-c", script], env=env, check=False, capture_output=True
        ).returncode
        == expected
    )
