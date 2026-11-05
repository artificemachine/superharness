"""Execute the workflow classifier and final gate with representative inputs."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/tests.yml"


@pytest.mark.parametrize("paths,expected", [
    (["README.md", "docs/guide.md"], True),
    (["docs/guide.rst"], True),
    (["requirements-dev.txt"], False),
    (["src/example.md"], False),
    (["docs/conf.py"], False),
    (["README.md", "src/main.py"], False),
    ([".github/workflows/tests.yml"], False),
    ([], False),
])
def test_classifier(tmp_path, monkeypatch, paths, expected):
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    code = jobs["changes"]["steps"][1]["run"]
    output = tmp_path / "output"
    monkeypatch.setenv("BASE_REF", "a" * 40)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    fixture = repr("\0".join(paths).encode())
    prefix = f"import subprocess; subprocess.check_output = lambda *a, **k: {fixture}\n"
    subprocess.run([sys.executable, "-c", prefix + code], check=True)
    assert output.read_text() == f"docs_only={str(expected).lower()}\n"


@pytest.mark.parametrize("docs,changes,shell,unit,expected", [
    ("true", "success", "success", "skipped", 0),
    ("true", "failure", "success", "skipped", 1),
    ("true", "success", "failure", "skipped", 1),
    ("false", "success", "success", "success", 0),
    ("false", "success", "success", "skipped", 1),
    ("false", "success", "success", "failure", 1),
])
def test_gate(docs, changes, shell, unit, expected):
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    env = dict(os.environ, DOCS_ONLY=docs, CHANGES_RESULT=changes,
               SHELL_TESTS=shell, UNIT_TESTS=unit,
               SMOKE_TESTS=unit, INTEGRATION_TESTS=unit,
               E2E_TESTS=unit, OTHER_TESTS=unit)
    result = subprocess.run(["bash", "-c", jobs["qa-gate"]["steps"][0]["run"]],
                            env=env, capture_output=True, text=True)
    assert result.returncode == expected, result.stdout + result.stderr


@pytest.mark.parametrize("operation,expected", [
    ("edit_docs", True), ("delete_docs", True),
    ("code_to_docs", False), ("docs_to_code", False),
])
def test_classifier_with_real_git(tmp_path, monkeypatch, operation, expected):
    code = yaml.safe_load(WORKFLOW.read_text())["jobs"]["changes"]["steps"][1]["run"]
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    def git(*args):
        return subprocess.check_output(["git", *args], stderr=subprocess.STDOUT).decode().strip()

    git("init", "-q")
    git("config", "user.name", "CI fixture")
    git("config", "user.email", "ci@example.invalid")
    git("config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (repo / "README.md").write_text("original\n")
    (repo / "main.py").write_text("print(1)\n")
    git("add", ".")
    git("-c", "commit.gpgsign=false", "commit", "-qm", "baseline")
    base = git("rev-parse", "HEAD")
    if operation == "edit_docs":
        (repo / "README.md").write_text("updated\n")
    elif operation == "delete_docs":
        (repo / "README.md").unlink()
    elif operation == "code_to_docs":
        (repo / "main.py").rename(repo / "example.md")
    else:
        (repo / "README.md").rename(repo / "example.py")
    git("add", "-A")
    git("-c", "commit.gpgsign=false", "commit", "-qm", "change")
    output = tmp_path / "output"
    monkeypatch.setenv("BASE_REF", base)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    subprocess.run([sys.executable, "-c", code], check=True)
    assert output.read_text() == f"docs_only={str(expected).lower()}\n"
