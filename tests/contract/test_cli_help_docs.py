"""Public documentation must stay aligned with the CLI help taxonomy."""

from __future__ import annotations

import re
from pathlib import Path

from superharness.commands.help_catalog import CORE_COMMANDS, DOMAIN_ENTRY_POINTS


ROOT = Path(__file__).parents[2]
README = (ROOT / "README.md").read_text()
GUIDE = (ROOT / "docs" / "GUIDE.md").read_text()


def test_readme_documents_core_workflow_and_help_all() -> None:
    assert "Core workflow" in README
    assert "shux help --all" in README
    for command in CORE_COMMANDS:
        assert f"shux {command}" in README


def test_readme_does_not_recreate_flat_command_dump() -> None:
    assert "shux adapter-payload --json" not in README
    assert "shux dashboard-kill" not in README


def test_guide_documents_all_four_domain_groups() -> None:
    for domain in DOMAIN_ENTRY_POINTS:
        assert f"### `{domain}`" in GUIDE
        assert f"shux {domain} --help" in GUIDE


def test_guide_uses_state_migrate_as_canonical_path() -> None:
    assert "shux state migrate --project ." in GUIDE
    assert "shux migrate-state --project ." in GUIDE


def test_docs_never_recommend_discussion_alias() -> None:
    assert re.search(r"\bshux discussion\b", README, re.I) is None
    assert re.search(r"\bshux discussion\b", GUIDE, re.I) is None
