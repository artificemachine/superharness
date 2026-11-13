"""Identify complete merge-group test evidence for an identical commit."""

import json
import os
import subprocess
import sys

REQUIRED_JOBS = frozenset(
    {
        f"{layer} ({os_name}-latest)"
        for layer in ("Smoke Tests", "Unit Tests", "Integration Tests", "E2E Tests")
        for os_name in ("ubuntu", "macos", "windows")
    }
    | {
        "Shell Test Suite",
        "Other Tests (chaos/contract/engine/perf/smoke-dir/state-machine/root)",
        "QA Gate",
    }
)


def complete_jobs(jobs: list[dict]) -> bool:
    matched = [job for job in jobs if job.get("name") in REQUIRED_JOBS]
    return (
        {job.get("name") for job in matched} == REQUIRED_JOBS
        and len(matched) == len(REQUIRED_JOBS)
        and all(
            job.get("status") == "completed" and job.get("conclusion") == "success"
            for job in jobs
        )
    )


def reusable_run(run: dict, sha: str) -> bool:
    return (
        run.get("event") == "merge_group"
        and run.get("head_sha") == sha
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    )


def has_reusable_evidence(runs: list[dict], jobs: list[dict], sha: str) -> bool:
    return len(runs) == 1 and reusable_run(runs[0], sha) and complete_jobs(jobs)


def lookup_evidence(event: str, sha: str, api) -> bool:
    if (
        event != "push"
        or len(sha) != 40
        or any(c not in "0123456789abcdef" for c in sha)
    ):
        return False
    try:
        response = api(
            f"actions/workflows/tests.yml/runs?head_sha={sha}&event=merge_group&per_page=100"
        )
        runs = response["workflow_runs"]
        if (
            response["total_count"] != 1
            or len(runs) != 1
            or not reusable_run(runs[0], sha)
        ):
            return False
        result = api(f"actions/runs/{int(runs[0]['id'])}/jobs?per_page=100")
        if result["total_count"] != len(result["jobs"]):
            return False
        return has_reusable_evidence(runs, result["jobs"], sha)
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        print(
            f"Cannot verify merge-group evidence; running full tests: {exc}",
            file=sys.stderr,
        )
        return False


def main() -> None:
    repo = os.environ["GITHUB_REPOSITORY"]

    def api(path: str) -> dict:
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/{path}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return json.loads(result.stdout)

    reuse = lookup_evidence(
        os.environ.get("GITHUB_EVENT_NAME", ""), os.environ.get("GITHUB_SHA", ""), api
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"reuse={'true' if reuse else 'false'}\n")


if __name__ == "__main__":
    main()
