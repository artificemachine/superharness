"""Iteration 2 of PLAN-prime-agent-adoptions.md — workflow policy regression
guard.

The repo's workflows are already SHA-pinned end to end and never leak a
secret above step scope (verified in `.github/workflows/release.yml`, the
exemplar). This contract test is a freeze: it fails CI the moment either
property regresses — an unpinned `uses:` reintroduced, or a `${{ secrets.* }}`
reference promoted from step-level `env:` to job- or workflow-level `env:`
(the latter would leak the secret into every step of the job/workflow rather
than the one step that needs it).

Scanner style mirrors tests/contract/test_source_ratchets.py: self-contained,
no production code dependency, repo-wide sweep as the contract.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

_SHA_PIN_RE = re.compile(r"@[0-9a-f]{40}$")


def _is_pinned_or_allowed(uses: str) -> bool:
    """A `uses:` reference is compliant if it is a local action (`./...`),
    a docker image reference (`docker://...`), or pinned to a full 40-hex
    commit SHA. Tag/branch refs like `@v7` or `@main` are not compliant."""
    if uses.startswith("./") or uses.startswith("docker://"):
        return True
    return bool(_SHA_PIN_RE.search(uses))


def _check_env_block(env: object, filename: str, scope_desc: str) -> list[str]:
    if not isinstance(env, dict):
        return []
    findings = []
    for key, value in env.items():
        if "secrets." in str(value):
            findings.append(
                f"{filename}: {scope_desc}-level env {key!r} references a secret "
                f"({value!r}) — secrets must only be set in step-level env"
            )
    return findings


def _iter_uses_findings(doc: dict, filename: str) -> list[str]:
    findings = []
    jobs = doc.get("jobs") or {}
    for job_name, job in jobs.items():
        steps = (job or {}).get("steps") or []
        for index, step in enumerate(steps):
            uses = (step or {}).get("uses")
            if uses is None:
                continue
            if not _is_pinned_or_allowed(uses):
                findings.append(
                    f"{filename}: job {job_name!r} step {index} has an unpinned "
                    f"action reference {uses!r} (must be pinned to a 40-hex SHA, "
                    f"or start with './' or 'docker://')"
                )
    return findings


def _iter_secret_env_findings(doc: dict, filename: str) -> list[str]:
    findings = []
    findings.extend(_check_env_block(doc.get("env"), filename, "workflow"))
    jobs = doc.get("jobs") or {}
    for job_name, job in jobs.items():
        findings.extend(
            _check_env_block((job or {}).get("env"), filename, f"job {job_name!r}")
        )
    return findings


def scan_workflow_text(text: str, filename: str = "<fixture>") -> list[str]:
    """Return a list of policy-violation strings for a workflow YAML document.
    Empty list means the document is compliant."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AssertionError(f"{filename}: could not be parsed as YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise AssertionError(f"{filename}: workflow YAML did not parse to a mapping")

    findings: list[str] = []
    findings.extend(_iter_uses_findings(doc, filename))
    findings.extend(_iter_secret_env_findings(doc, filename))
    return findings


def scan_workflow_file(path: Path) -> list[str]:
    return scan_workflow_text(path.read_text(), filename=path.name)


def iter_workflow_files() -> list[Path]:
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


# --- fixture-driven unit tests -------------------------------------------


def test_scanner_flags_unpinned_action() -> None:
    fixture = """
jobs:
  build:
    steps:
      - uses: actions/checkout@v7
"""
    findings = scan_workflow_text(fixture, filename="fixture.yml")
    assert len(findings) == 1, findings
    assert "actions/checkout@v7" in findings[0]


def test_scanner_accepts_sha_pinned_action() -> None:
    fixture = """
jobs:
  build:
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
"""
    findings = scan_workflow_text(fixture, filename="fixture.yml")
    assert findings == []


def test_scanner_allows_local_and_docker_actions() -> None:
    fixture = """
jobs:
  build:
    steps:
      - uses: ./.github/actions/foo
      - uses: docker://alpine
"""
    findings = scan_workflow_text(fixture, filename="fixture.yml")
    assert findings == []


def test_scanner_flags_workflow_or_job_level_secret_env() -> None:
    job_level = """
jobs:
  build:
    env:
      TOKEN: ${{ secrets.GITHUB_TOKEN }}
    steps:
      - run: echo hi
"""
    findings = scan_workflow_text(job_level, filename="fixture.yml")
    assert len(findings) == 1, findings
    assert "job 'build'" in findings[0]

    workflow_level = """
env:
  TOKEN: ${{ secrets.GITHUB_TOKEN }}
jobs:
  build:
    steps:
      - run: echo hi
"""
    findings = scan_workflow_text(workflow_level, filename="fixture.yml")
    assert len(findings) == 1, findings
    assert "workflow-level" in findings[0]

    step_level = """
jobs:
  build:
    steps:
      - name: use token
        env:
          TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: echo hi
"""
    findings = scan_workflow_text(step_level, filename="fixture.yml")
    assert findings == []


def test_scanner_reports_malformed_yaml() -> None:
    malformed = "jobs: [this is not: valid yaml: at all: ["
    with pytest.raises(AssertionError, match="broken.yml"):
        scan_workflow_text(malformed, filename="broken.yml")


# --- repo-wide freeze -------------------------------------------------


def test_all_repo_workflows_pass_policy() -> None:
    files = iter_workflow_files()
    assert files, "no workflow files found under .github/workflows/"

    all_findings: list[str] = []
    for path in files:
        all_findings.extend(scan_workflow_file(path))

    assert not all_findings, "workflow policy violations:\n" + "\n".join(all_findings)
