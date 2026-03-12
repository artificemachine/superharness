from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT, run_bash

TEMPLATE_DIR = REPO_ROOT / "protocol" / "templates"
SOUL_TEMPLATE = TEMPLATE_DIR / "SOUL.md.template"
CLAUDE_TEMPLATE = TEMPLATE_DIR / "CLAUDE.md.template"
AGENTS_TEMPLATE = TEMPLATE_DIR / "AGENTS.md.template"


# ---------------------------------------------------------------------------
# Template existence and content
# ---------------------------------------------------------------------------


def test_soul_template_exists() -> None:
    assert SOUL_TEMPLATE.exists(), f"Missing: {SOUL_TEMPLATE}"


def test_soul_template_has_guardrails() -> None:
    assert SOUL_TEMPLATE.exists(), "Template not found — run test_soul_template_exists first"
    text = SOUL_TEMPLATE.read_text()
    assert "Guardrails" in text, "SOUL.md.template must contain a 'Guardrails' section"


def test_soul_template_has_identity() -> None:
    assert SOUL_TEMPLATE.exists(), "Template not found"
    text = SOUL_TEMPLATE.read_text()
    assert "Identity" in text, "SOUL.md.template must contain an 'Identity' section"


# ---------------------------------------------------------------------------
# init-project.sh integration
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_project(tmp_path: Path) -> Path:
    """A temporary directory with no prior superharness init."""
    project = tmp_path / "test-soul-project"
    project.mkdir()
    return project


def _run_init(project: Path, project_name: str = "SoulTest") -> subprocess.CompletedProcess[str]:
    script = REPO_ROOT / "init-project.sh"
    return run_bash(script, cwd=project, args=[project_name, "Python", "greenfield"])


def test_init_creates_soul_md(fresh_project: Path) -> None:
    result = _run_init(fresh_project)
    assert result.returncode == 0, result.stderr
    soul = fresh_project / "SOUL.md"
    assert soul.exists(), "init-project.sh should create SOUL.md"


def test_init_soul_md_has_project_name(fresh_project: Path) -> None:
    result = _run_init(fresh_project, project_name="MyAwesomeProject")
    assert result.returncode == 0, result.stderr
    soul = fresh_project / "SOUL.md"
    assert soul.exists(), "SOUL.md must be created"
    content = soul.read_text()
    assert "MyAwesomeProject" in content, "SOUL.md must contain the project name"


def test_init_skips_soul_md_if_exists(fresh_project: Path) -> None:
    sentinel = "# pre-existing soul content — do not overwrite\n"
    soul = fresh_project / "SOUL.md"
    soul.write_text(sentinel)

    result = _run_init(fresh_project)
    assert result.returncode == 0, result.stderr
    assert soul.read_text() == sentinel, "init-project.sh must not overwrite an existing SOUL.md"
    assert "Skipped: SOUL.md" in result.stdout, "init should report 'Skipped: SOUL.md'"


def test_soul_md_has_operating_constraints(fresh_project: Path) -> None:
    result = _run_init(fresh_project)
    assert result.returncode == 0, result.stderr
    soul = fresh_project / "SOUL.md"
    assert soul.exists()
    content = soul.read_text()
    has_constraints = "Operating Constraints" in content or "Guardrails" in content
    assert has_constraints, "SOUL.md must contain 'Operating Constraints' or 'Guardrails'"


# ---------------------------------------------------------------------------
# Template cross-references
# ---------------------------------------------------------------------------


def test_claude_md_template_references_soul() -> None:
    if not CLAUDE_TEMPLATE.exists():
        pytest.skip("CLAUDE.md.template not present")
    text = CLAUDE_TEMPLATE.read_text()
    assert "SOUL.md" in text, "CLAUDE.md.template must reference SOUL.md"


def test_agents_md_template_references_soul() -> None:
    if not AGENTS_TEMPLATE.exists():
        pytest.skip("AGENTS.md.template not present")
    text = AGENTS_TEMPLATE.read_text()
    assert "SOUL.md" in text, "AGENTS.md.template must reference SOUL.md"
