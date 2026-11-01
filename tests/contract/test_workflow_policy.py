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

import json
import os
import re
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

_SHA_PIN_RE = re.compile(r"@[0-9a-f]{40}$")


class _GitHubActionsLoader(yaml.SafeLoader):
    pass


_GitHubActionsLoader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_GitHubActionsLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$", re.IGNORECASE), list("tTfF")
)


def _load_workflow(text: str) -> dict:
    try:
        loader = _GitHubActionsLoader(text)
        try:
            doc = loader.get_single_data()
        finally:
            loader.dispose()
    except yaml.YAMLError as exc:
        raise AssertionError(f"could not be parsed as workflow YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise AssertionError("workflow YAML did not parse to a mapping")
    return doc


def test_workflow_loader_keeps_yaml_12_and_rejects_python_tags(capsys) -> None:
    workflow = _load_workflow("on:\n  push: {}\nflag: true\n")
    assert "on" in workflow
    assert workflow["flag"] is True

    tagged_object = "payload: !!python/object/apply:builtins.print ['executed']\n"
    with pytest.raises(AssertionError, match="could not be parsed as workflow YAML"):
        _load_workflow(tagged_object)
    assert capsys.readouterr().out == ""


def _publication_policy_findings(release_text: str, publish_text: str) -> list[str]:
    release = _load_workflow(release_text)
    publish = _load_workflow(publish_text)
    findings = []
    if set(publish.get("on", {})) != {"workflow_dispatch"}:
        findings.append("publish workflow must be manual-dispatch only")
    for job_name, job in (release.get("jobs") or {}).items():
        for step in (job or {}).get("steps") or []:
            run = (step or {}).get("run", "")
            if re.search(r"\bgh\s+workflow\s+run\s+publish\.yml\b", run):
                findings.append(f"release workflow job {job_name!r} dispatches publication")
    return findings


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


def test_publication_requires_explicit_dispatch() -> None:
    release = (WORKFLOWS_DIR / "release.yml").read_text()
    publish = (WORKFLOWS_DIR / "publish.yml").read_text()
    assert _publication_policy_findings(release, publish) == []

    safe_release = "on:\n  workflow_dispatch: {}\njobs:\n  release:\n    steps:\n      - run: gh release create v1.2.3\n"
    safe_publish = "on:\n  workflow_dispatch: {}\njobs:\n  publish:\n    steps:\n      - run: python publish.py\n"
    assert _publication_policy_findings(safe_release, safe_publish) == []

    unsafe_release = "on:\n  workflow_dispatch: {}\njobs:\n  release:\n    steps:\n      - run: gh workflow run publish.yml\n"
    unsafe_publish = "on:\n  release:\n    types: [published]\n  workflow_dispatch: {}\njobs: {}\n"
    findings = _publication_policy_findings(unsafe_release, unsafe_publish)
    assert len(findings) == 2, findings
    assert any("dispatches publication" in finding for finding in findings)
    assert any("manual-dispatch only" in finding for finding in findings)


@pytest.fixture
def gitleaks_scan_harness(tmp_path: Path) -> dict:
    workflow = _load_workflow((WORKFLOWS_DIR / "security.yml").read_text())
    steps = workflow["jobs"]["gitleaks"]["steps"]
    scan = next(step for step in steps if step.get("name") == "Gitleaks secret scan")

    repo = tmp_path / "repo"
    repo.mkdir()
    git_env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
            env=git_env,
        )
        return result.stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Workflow Fixture")
    git("config", "user.email", "workflow-fixture@example.invalid")
    commit_ids = []
    for marker in ("baseline", "middle", "new"):
        (repo / "marker.txt").write_text(marker)
        git("add", "marker.txt")
        git("commit", "-q", "-m", marker)
        commit_ids.append(git("rev-parse", "HEAD"))
    baseline, middle, new_commit = commit_ids

    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    fake_gitleaks = mock_bin / "gitleaks"
    fake_gitleaks.write_text(
        f"#!{sys.executable}\n"
        "import json, os, subprocess, sys\n"
        "args = sys.argv[1:]\n"
        "if args == ['version']:\n"
        "    print(os.environ.get('MOCK_GITLEAKS_VERSION', '8.30.1'))\n"
        "    raise SystemExit(0)\n"
        "opts = next((arg.split('=', 1)[1] for arg in args if arg.startswith('--log-opts=')), None)\n"
        "rev = opts or 'HEAD'\n"
        "commits = subprocess.check_output(['git', 'rev-list', rev], text=True).splitlines()\n"
        "with open(os.environ['SCAN_LOG'], 'a') as f:\n"
        "    f.write(json.dumps({'args': args, 'commits': commits}) + '\\n')\n"
        "print('fixture scan completed')\n"
        "raise SystemExit(int(os.environ.get('MOCK_GITLEAKS_EXIT', '0')))\n"
    )
    fake_gitleaks.chmod(0o755)

    def scan_result(
        name: str,
        event: str,
        before: str = "",
        pr_base: str = "",
        merge_base: str = "",
        exit_code: str = "0",
    ):
        log_path = tmp_path / f"{name}.jsonl"
        environment = {
            **git_env,
            "PATH": f"{mock_bin}:{git_env['PATH']}",
            "EVENT_NAME": event,
            "EVENT_BEFORE": before,
            "PR_BASE_SHA": pr_base,
            "MERGE_GROUP_BASE_SHA": merge_base,
            "SCAN_LOG": str(log_path),
            "MOCK_GITLEAKS_EXIT": exit_code,
        }
        result = subprocess.run(
            ["bash", "-e", "-c", scan["run"]],
            cwd=repo,
            capture_output=True,
            text=True,
            env=environment,
        )
        records = (
            [json.loads(line) for line in log_path.read_text().splitlines()]
            if log_path.exists()
            else []
        )
        return result, records

    return {
        "scan": scan,
        "scan_result": scan_result,
        "commits": {"baseline": baseline, "middle": middle, "new": new_commit},
    }


@pytest.mark.parametrize(
    ("event", "before", "pr_base", "merge_base", "expected"),
    [
        pytest.param("push", "middle", "", "", "new", id="push-before-to-head"),
        pytest.param("pull_request", "", "middle", "", "new", id="pull-request-base"),
        pytest.param("merge_group", "", "", "baseline", "new-middle", id="merge-group-base"),
        pytest.param("push", "", "", "", "full-history", id="push-missing-before"),
        pytest.param("push", "zero", "", "", "full-history", id="push-zero-before"),
    ],
)
def test_push_scan_is_nonempty_and_integrity_checked(
    gitleaks_scan_harness: dict,
    event: str,
    before: str,
    pr_base: str,
    merge_base: str,
    expected: str,
) -> None:
    harness = gitleaks_scan_harness
    commits = harness["commits"]
    refs = {"baseline": commits["baseline"], "middle": commits["middle"]}
    before_value = "0" * 40 if before == "zero" else refs.get(before, before)
    pr_value = refs.get(pr_base, pr_base)
    merge_value = refs.get(merge_base, merge_base)
    expected_commits = {
        "new": [commits["new"]],
        "new-middle": [commits["new"], commits["middle"]],
        "full-history": [commits["new"], commits["middle"], commits["baseline"]],
    }[expected]

    result, records = harness["scan_result"](
        f"{event}-{before}-{pr_base}-{merge_base}",
        event,
        before_value,
        pr_value,
        merge_value,
    )
    assert result.returncode == 0, result.stderr
    assert len(records) == 1, records
    assert records[0]["commits"] == expected_commits
    if expected == "full-history":
        assert not any(arg.startswith("--log-opts=") for arg in records[0]["args"])
    else:
        base = {
            "push": before_value,
            "pull_request": pr_value,
            "merge_group": merge_value,
        }[event]
        assert f"--log-opts={base}..HEAD" in records[0]["args"]


@pytest.mark.parametrize(
    ("event", "before", "pr_base", "merge_base"),
    [
        pytest.param("push", "f" * 40, "", "", id="missing-push-commit"),
        pytest.param("pull_request", "", "", "", id="missing-pull-request-base"),
        pytest.param("pull_request", "", "f" * 40, "", id="missing-pr-commit"),
        pytest.param("merge_group", "", "", "", id="missing-merge-group-base"),
        pytest.param("merge_group", "", "", "f" * 40, id="missing-merge-commit"),
        pytest.param("schedule", "", "", "", id="unexpected-event"),
    ],
)
def test_secret_scan_fails_closed_without_event_base(
    gitleaks_scan_harness: dict,
    event: str,
    before: str,
    pr_base: str,
    merge_base: str,
) -> None:
    result, records = gitleaks_scan_harness["scan_result"](
        f"invalid-{event}-{before}-{pr_base}-{merge_base}",
        event,
        before,
        pr_base,
        merge_base,
    )
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert records == []


def test_secret_scan_preserves_scanner_failure(gitleaks_scan_harness: dict) -> None:
    commits = gitleaks_scan_harness["commits"]
    result, records = gitleaks_scan_harness["scan_result"](
        "scanner-failure", "push", commits["middle"], exit_code="23"
    )
    assert result.returncode == 23, (result.stdout, result.stderr)
    assert records[0]["commits"] == [commits["new"]]
    assert "fixture scan completed" in result.stdout
    assert (gitleaks_scan_harness["scan"]["env"]) == {
        "EVENT_NAME": "${{ github.event_name }}",
        "EVENT_BEFORE": "${{ github.event.before }}",
        "PR_BASE_SHA": "${{ github.event.pull_request.base.sha }}",
        "MERGE_GROUP_BASE_SHA": "${{ github.event.merge_group.base_sha }}",
    }
    assert "${{" not in gitleaks_scan_harness["scan"]["run"]


@pytest.fixture
def gitleaks_install_harness(tmp_path: Path) -> dict:
    steps = _load_workflow((WORKFLOWS_DIR / "security.yml").read_text())["jobs"]["gitleaks"]["steps"]
    install = next(step for step in steps if step.get("name") == "Install gitleaks (MIT-licensed CLI)")
    install_env = install.get("env") or {}
    install_bin = tmp_path / "install-bin"
    install_bin.mkdir()
    install_log = tmp_path / "install.log"

    def fake_tool(name: str, source: str) -> None:
        path = install_bin / name
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)

    fake_tool("curl", "import pathlib, sys\noutput = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\noutput.write_bytes(b'fixture archive')\n")
    fake_tool(
        "sha256sum",
        "import os, sys\n"
        "line = sys.stdin.read().strip()\n"
        "expected, filename = line.split(maxsplit=1)\n"
        "with open(os.environ['INSTALL_LOG'], 'a') as log: log.write('sha:' + expected + '\\n')\n"
        "if expected != os.environ['EXPECTED_GITLEAKS_SHA256']:\n"
        "    raise SystemExit(2)\n"
        "if os.environ.get('MOCK_CHECKSUM_MODE') == 'fail':\n"
        "    print(filename + ': FAILED')\n"
        "    raise SystemExit(1)\n"
        "print(filename + ': OK')\n",
    )
    fake_tool(
        "tar",
        "import os, pathlib, sys\n"
        "with open(os.environ['INSTALL_LOG'], 'a') as log: log.write('tar\\n')\n"
        "binary = '#!' + sys.executable + '\\n'\n"
        "binary += 'import os, sys\\n'\n"
        "binary += 'if len(sys.argv) > 1 and sys.argv[1] == \"version\":\\n'\n"
        "binary += '    with open(os.environ[\"INSTALL_LOG\"], \"a\") as log: log.write(\"version\\\\n\")\\n'\n"
        "binary += '    print(os.environ.get(\"MOCK_GITLEAKS_VERSION\", \"8.30.1\"))\\n'\n"
        "binary += '    raise SystemExit(0)\\n'\n"
        "binary += 'raise SystemExit(3)\\n'\n"
        "pathlib.Path('gitleaks').write_text(binary)\n"
        "pathlib.Path('gitleaks').chmod(0o755)\n",
    )
    fake_tool(
        "sudo",
        "import os, pathlib, shutil, sys\n"
        "with open(os.environ['INSTALL_LOG'], 'a') as log: log.write('sudo\\n')\n"
        "if sys.argv[1:3] != ['mv', 'gitleaks']:\n"
        "    raise SystemExit(2)\n"
        "shutil.move('gitleaks', pathlib.Path(os.environ['MOCK_BIN']) / 'gitleaks')\n",
    )

    def install_result(name: str, checksum_mode: str, version: str):
        mock_bin = tmp_path / f"{name}-bin"
        mock_bin.mkdir()
        expected_sha = install_env["GITLEAKS_SHA256"].strip()
        environment = {
            "PATH": f"{install_bin}:{mock_bin}:{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GITLEAKS_VERSION": install_env["GITLEAKS_VERSION"].strip('"'),
            "GITLEAKS_SHA256": expected_sha,
            "EXPECTED_GITLEAKS_SHA256": expected_sha,
            "MOCK_CHECKSUM_MODE": checksum_mode,
            "MOCK_GITLEAKS_VERSION": version,
            "MOCK_BIN": str(mock_bin),
            "INSTALL_LOG": str(install_log),
        }
        log_start = len(install_log.read_text().splitlines()) if install_log.exists() else 0
        result = subprocess.run(
            ["bash", "-e", "-c", install["run"]],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=environment,
        )
        records = install_log.read_text().splitlines()[log_start:] if install_log.exists() else []
        return result, records

    return {"install": install, "env": install_env, "run": install_result}


def test_required_gitleaks_install_uses_pinned_artifact(gitleaks_install_harness: dict) -> None:
    install_env = gitleaks_install_harness["env"]
    expected_sha = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
    assert install_env["GITLEAKS_VERSION"].strip('"') == "8.30.1"
    assert install_env["GITLEAKS_SHA256"].strip() == expected_sha
    exemplar = _load_workflow((WORKFLOWS_DIR / "gitleaks.yml").read_text())
    exemplar_install = next(
        step for step in exemplar["jobs"]["scan"]["steps"] if step.get("name") == "Install gitleaks"
    )
    assert install_env == exemplar_install["env"]


def test_gitleaks_install_stops_before_extract_on_checksum_mismatch(
    gitleaks_install_harness: dict,
) -> None:
    result, records = gitleaks_install_harness["run"]("bad_checksum", "fail", "8.30.1")
    assert result.returncode != 0
    assert "tar" not in records and "sudo" not in records and "version" not in records


def test_gitleaks_install_rejects_wrong_version(gitleaks_install_harness: dict) -> None:
    result, records = gitleaks_install_harness["run"]("wrong_version", "pass", "8.30.2")
    assert result.returncode != 0
    assert "tar" in records and "version" in records
    assert "expected gitleaks 8.30.1" in result.stderr


def test_gitleaks_install_accepts_pinned_version(gitleaks_install_harness: dict) -> None:
    result, records = gitleaks_install_harness["run"]("valid_install", "pass", "8.30.1")
    assert result.returncode == 0, result.stderr
    assert "gitleaks 8.30.1" in result.stdout
    assert "tar" in records and "version" in records



_EXPECTED_REQUIRED_CHECKS = (
    "QA Gate",
    "Windows-Native Release Gate",
    "ShipGuard Scan",
    "Gitleaks",
    "doctrine",
    "scan",
    "Analyze (python)",
)


@pytest.fixture
def required_gate_harness(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "if os.environ.get('GH_API_FAIL') == '1':\n"
        "    print('fixture API failure', file=sys.stderr)\n"
        "    raise SystemExit(17)\n"
        "with open(os.environ['CHECK_RUNS_FIXTURE']) as fixture:\n"
        "    data = json.load(fixture)\n"
        "fields = ('name', 'conclusion', 'started_at')\n"
        "if any('status' in arg for arg in sys.argv): fields += ('status',)\n"
        "for run in data['check_runs']:\n"
        "    print(json.dumps({key: run.get(key) for key in fields}))\n"
    )
    fake_gh.chmod(0o755)
    gate = REPO_ROOT / "scripts" / "required_checks_gate.sh"

    def run(check_runs: list[dict], api_failure: bool = False):
        fixture = tmp_path / "check-runs.json"
        fixture.write_text(json.dumps({"check_runs": check_runs}))
        environment = {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GITHUB_REPOSITORY": "fixture/project",
            "CHECK_RUNS_FIXTURE": str(fixture),
            "GH_API_FAIL": "1" if api_failure else "0",
        }
        return subprocess.run(
            ["bash", str(gate), "a" * 40],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=environment,
        )

    return run


def _successful_required_runs() -> list[dict]:
    return [
        {
            "name": name,
            "status": "completed",
            "conclusion": "success",
            "started_at": f"2026-11-01T00:00:{index:02d}Z",
        }
        for index, name in enumerate(_EXPECTED_REQUIRED_CHECKS)
    ]


@pytest.mark.parametrize("missing", _EXPECTED_REQUIRED_CHECKS[4:])
def test_required_checks_include_doctrine_and_scanners(
    required_gate_harness, missing: str
) -> None:
    runs = [run for run in _successful_required_runs() if run["name"] != missing]
    result = required_gate_harness(runs)
    assert result.returncode != 0, (missing, result.stdout, result.stderr)
    assert missing in result.stdout


def test_required_check_gate_accepts_all_success(required_gate_harness) -> None:
    result = required_gate_harness(_successful_required_runs())
    assert result.returncode == 0, result.stderr
    assert "All required checks green" in result.stdout


@pytest.mark.parametrize(
    ("conclusion", "status"),
    (
        pytest.param("failure", "completed", id="failure"),
        pytest.param("cancelled", "completed", id="cancelled"),
        pytest.param("skipped", "completed", id="skipped"),
        pytest.param(None, "in_progress", id="running"),
    ),
)
def test_required_check_gate_blocks_non_success(
    required_gate_harness, conclusion: str | None, status: str
) -> None:
    runs = _successful_required_runs()
    next(run for run in runs if run["name"] == "scan").update(
        conclusion=conclusion, status=status
    )
    result = required_gate_harness(runs)
    assert result.returncode != 0, (conclusion, result.stdout, result.stderr)
    assert "scan" in result.stdout


@pytest.mark.parametrize(
    ("latest_conclusion", "expected_success"),
    (("failure", False), ("success", True)),
)
def test_required_check_gate_uses_latest_rerun(
    required_gate_harness, latest_conclusion: str, expected_success: bool
) -> None:
    runs = _successful_required_runs()
    runs.append(
        {
            "name": "doctrine",
            "status": "completed",
            "conclusion": latest_conclusion,
            "started_at": "2026-11-01T00:01:00Z",
        }
    )
    runs.append(
        {
            "name": "doctrine",
            "status": "completed",
            "conclusion": "failure",
            "started_at": "2026-11-01T00:00:01Z",
        }
    )
    result = required_gate_harness(runs)
    assert (result.returncode == 0) is expected_success, (result.stdout, result.stderr)


def test_required_check_gate_blocks_queued_rerun_after_old_success(
    required_gate_harness,
) -> None:
    runs = _successful_required_runs()
    runs.append(
        {"name": "scan", "conclusion": None, "started_at": None, "status": "queued"}
    )
    result = required_gate_harness(runs)
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert "scan" in result.stdout


def test_required_check_gate_blocks_unranked_cancelled_rerun(
    required_gate_harness,
) -> None:
    runs = _successful_required_runs()
    runs.append(
        {"name": "scan", "status": "completed", "conclusion": "cancelled", "started_at": None}
    )
    result = required_gate_harness(runs)
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert "scan" in result.stdout


def test_required_check_gate_fails_on_api_error(required_gate_harness) -> None:
    result = required_gate_harness([], api_failure=True)
    assert result.returncode != 0
    assert "fixture API failure" in result.stderr


def _render_matrix_group(concurrency: dict, workflow_name: str, ref: str) -> str | None:
    group = concurrency.get("group")
    if not isinstance(group, str) or not group.strip():
        return None
    rendered = group.replace("${{ github.workflow }}", workflow_name).replace(
        "${{ github.ref }}", ref
    )
    return None if "${{" in rendered else rendered


def _matrix_policy_isolated(workflow: dict, workflow_name: str) -> bool:
    concurrency = workflow.get("concurrency")
    if not isinstance(concurrency, dict) or concurrency.get("cancel-in-progress") is not True:
        return False

    pr_ref = "refs/pull/41/merge"
    same_ref_group = _render_matrix_group(concurrency, workflow_name, pr_ref)
    repeated_ref_group = _render_matrix_group(concurrency, workflow_name, pr_ref)
    distinct_pr_group = _render_matrix_group(
        concurrency, workflow_name, "refs/pull/42/merge"
    )
    merge_group_a = _render_matrix_group(
        concurrency, workflow_name, "refs/heads/gh-readonly-queue/main/pr-41"
    )
    merge_group_b = _render_matrix_group(
        concurrency, workflow_name, "refs/heads/gh-readonly-queue/main/pr-42"
    )
    other_workflow_group = _render_matrix_group(
        concurrency, "Other Workflow", pr_ref
    )
    isolated_groups = (
        same_ref_group,
        distinct_pr_group,
        merge_group_a,
        merge_group_b,
        other_workflow_group,
    )
    return (
        same_ref_group is not None
        and same_ref_group == repeated_ref_group
        and None not in isolated_groups
        and len(set(isolated_groups)) == len(isolated_groups)
    )


def test_matrix_workflows_cancel_superseded_runs() -> None:
    workflow_paths = (
        WORKFLOWS_DIR / "tests.yml",
        WORKFLOWS_DIR / "ci-matrix.yml",
    )
    for path in workflow_paths:
        workflow = _load_workflow(path.read_text())
        assert set(workflow.get("on", {})) == {"merge_group", "pull_request", "push"}
        assert _matrix_policy_isolated(workflow, workflow["name"]), path.name

    positive_fixture = _load_workflow(
        "name: Synthetic Matrix\non:\n  merge_group: {}\n  pull_request: {}\n"
        "  push: {}\nconcurrency:\n  group: '${{ github.workflow }}-${{ github.ref }}'\n"
        "  cancel-in-progress: true\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps: []\n"
    )
    assert _matrix_policy_isolated(positive_fixture, positive_fixture["name"])

    negative_fixtures = (
        "name: Missing Group\nconcurrency:\n  cancel-in-progress: true\n",
        "name: Missing Ref\nconcurrency:\n  group: '${{ github.workflow }}'\n"
        "  cancel-in-progress: true\n",
        "name: Missing Workflow\nconcurrency:\n  group: '${{ github.ref }}'\n"
        "  cancel-in-progress: true\n",
        "name: Cancellation Disabled\nconcurrency:\n  group: '${{ github.workflow }}-${{ github.ref }}'\n"
        "  cancel-in-progress: false\n",
    )
    for fixture in negative_fixtures:
        assert not _matrix_policy_isolated(_load_workflow(fixture), "Synthetic Matrix")


def test_security_shell_workflows_cancel_superseded_runs() -> None:
    workflow_paths = (
        WORKFLOWS_DIR / "security.yml",
        WORKFLOWS_DIR / "shell-guard.yml",
    )
    for path in workflow_paths:
        workflow = _load_workflow(path.read_text())
        assert set(workflow.get("on", {})) == {"merge_group", "pull_request", "push"}
        assert _matrix_policy_isolated(workflow, workflow["name"]), path.name

    safe_fixture = _load_workflow(
        "name: Synthetic Security\nconcurrency:\n"
        "  group: '${{ github.workflow }}-${{ github.ref }}'\n"
        "  cancel-in-progress: true\n"
    )
    assert _matrix_policy_isolated(safe_fixture, safe_fixture["name"])

    unsafe_fixtures = (
        "name: Missing Group\nconcurrency:\n  cancel-in-progress: true\n",
        "name: Shared Refs\nconcurrency:\n  group: '${{ github.workflow }}'\n"
        "  cancel-in-progress: true\n",
        "name: Cancellation Disabled\nconcurrency:\n"
        "  group: '${{ github.workflow }}-${{ github.ref }}'\n"
        "  cancel-in-progress: false\n",
    )
    for fixture in unsafe_fixtures:
        assert not _matrix_policy_isolated(_load_workflow(fixture), "Synthetic Security")

    publish = _load_workflow((WORKFLOWS_DIR / "publish.yml").read_text())
    assert publish.get("concurrency", {}).get("cancel-in-progress") is not True


# --- repo-wide freeze -------------------------------------------------


def test_all_repo_workflows_pass_policy() -> None:
    files = iter_workflow_files()
    assert files, "no workflow files found under .github/workflows/"

    all_findings: list[str] = []
    for path in files:
        all_findings.extend(scan_workflow_file(path))

    assert not all_findings, "workflow policy violations:\n" + "\n".join(all_findings)
