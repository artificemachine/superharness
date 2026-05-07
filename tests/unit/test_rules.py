"""Tests for shux rules — project self-configuration (Pi-style).

Verifies:
  - Rules are parsed correctly from .superharness/rules/*.md
  - CLI commands work (list, show, search)
  - Rules auto-inject into adapter payloads
  - Rules auto-inject into handoffs
  - CLAUDE.md references rules
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from superharness.commands.rules import (
    list_rules,
    show_rule,
    search_rules,
    all_rules_text,
    _parse_rule,
)


@pytest.fixture
def rules_project(tmp_path: Path) -> Path:
    """Project with .superharness/rules/ containing test rule files."""
    project = tmp_path / "proj"
    rules_dir = project / ".superharness" / "rules"
    rules_dir.mkdir(parents=True)

    (rules_dir / "alpha.md").write_text("""---
id: alpha
title: Rule Alpha
status: active
since: v1.0
---

Alpha body content. This rule covers state backend policy.
""")

    (rules_dir / "beta.md").write_text("""---
id: beta
title: Rule Beta
status: deprecated
since: v0.5
---

Beta body. Covers changelog policy.
""")

    (rules_dir / "no-frontmatter.md").write_text("No frontmatter here.")
    return project


class TestRuleParsing:
    def test_parse_valid_rule(self, rules_project: Path):
        rule = _parse_rule(rules_project / ".superharness" / "rules" / "alpha.md")
        assert rule is not None
        assert rule["id"] == "alpha"
        assert rule["title"] == "Rule Alpha"
        assert rule["status"] == "active"
        assert rule["since"] == "v1.0"
        assert "Alpha body content" in rule["_body"]

    def test_parse_no_frontmatter(self, rules_project: Path):
        rule = _parse_rule(rules_project / ".superharness" / "rules" / "no-frontmatter.md")
        assert rule is None

    def test_parse_nonexistent_file(self, rules_project: Path):
        rule = _parse_rule(rules_project / ".superharness" / "rules" / "nope.md")
        assert rule is None


class TestListRules:
    def test_list_all(self, rules_project: Path):
        rules = list_rules(str(rules_project))
        assert len(rules) == 2  # alpha + beta, no-frontmatter excluded
        ids = {r["id"] for r in rules}
        assert ids == {"alpha", "beta"}

    def test_list_empty_dir(self, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        (empty / ".superharness" / "rules").mkdir(parents=True)
        rules = list_rules(str(empty))
        assert rules == []

    def test_list_no_dir(self, tmp_path: Path):
        rules = list_rules(str(tmp_path / "nonexistent"))
        assert rules == []


class TestShowRule:
    def test_show_existing(self, rules_project: Path):
        content = show_rule("alpha", str(rules_project))
        assert content is not None
        assert "id: alpha" in content
        assert "Alpha body content" in content

    def test_show_nonexistent(self, rules_project: Path):
        content = show_rule("nope", str(rules_project))
        assert content is None


class TestSearchRules:
    def test_search_finds_match(self, rules_project: Path):
        results = search_rules("state backend", str(rules_project))
        assert len(results) == 1
        assert results[0]["id"] == "alpha"

    def test_search_no_match(self, rules_project: Path):
        results = search_rules("xyzzy_nonexistent", str(rules_project))
        assert results == []

    def test_search_case_insensitive(self, rules_project: Path):
        results = search_rules("CHANGELOG", str(rules_project))
        assert len(results) == 1
        assert results[0]["id"] == "beta"


class TestAllRulesText:
    def test_returns_all_rules(self, rules_project: Path):
        text = all_rules_text(str(rules_project))
        assert "id: alpha" in text
        assert "id: beta" in text
        assert "No frontmatter here" not in text  # excluded (no frontmatter)

    def test_empty_dir(self, tmp_path: Path):
        empty = tmp_path / "empty"
        (empty / ".superharness" / "rules").mkdir(parents=True)
        text = all_rules_text(str(empty))
        assert text == ""


class TestAdapterPayloadRules:
    def test_build_payload_includes_rules(self, rules_project: Path):
        """Adapter payload must include rules key for Morpheme/external consumers."""
        from superharness.commands.adapter_payload import build_payload
        payload = build_payload(str(rules_project))
        assert "rules" in payload
        rules = payload["rules"]
        assert "id: alpha" in rules
        assert "id: beta" in rules

    def test_build_payload_no_rules_dir(self, tmp_path: Path):
        """Payload still works when no rules directory exists."""
        from superharness.commands.adapter_payload import build_payload
        payload = build_payload(str(tmp_path))
        assert "rules" in payload
        assert payload["rules"] == ""


class TestHandoffRules:
    def test_load_rules_function(self, rules_project: Path):
        """_load_rules loads project rules for handoff injection."""
        from superharness.engine.handoff_generator import _load_rules
        rules = _load_rules(str(rules_project))
        assert "id: alpha" in rules
        assert "id: beta" in rules

    def test_load_rules_no_dir(self, tmp_path: Path):
        from superharness.engine.handoff_generator import _load_rules
        rules = _load_rules(str(tmp_path))
        assert rules == ""


class TestCLAUDEMdReferencesRules:
    def test_claude_md_mentions_shux_rules(self):
        """CLAUDE.md must instruct agents to use shux rules."""
        # tests/unit/test_rules.py → tests/ → superharness/ → CLAUDE.md
        claude_path = Path(__file__).resolve().parents[2] / "CLAUDE.md"
        if not claude_path.exists():
            pytest.skip("CLAUDE.md not found at repo root")
        content = claude_path.read_text()
        assert "shux rules" in content, "CLAUDE.md must reference shux rules"
        assert "State lives in SQLite" in content or "contract.yaml" in content


class TestRealProjectRules:
    """Integration: verify the real project's rules are valid."""

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[2]

    def test_real_rules_exist(self):
        rules_dir = self._repo_root() / ".superharness" / "rules"
        if not rules_dir.exists():
            pytest.skip(".superharness/rules/ not found")
        files = list(rules_dir.glob("*.md"))
        assert len(files) >= 4, f"Expected at least 4 rule files, got {len(files)}"

    def test_real_rules_parse(self):
        rules_dir = self._repo_root() / ".superharness" / "rules"
        if not rules_dir.exists():
            pytest.skip(".superharness/rules/ not found")
        for f in sorted(rules_dir.glob("*.md")):
            rule = _parse_rule(f)
            assert rule is not None, f"Failed to parse {f.name}"
            assert rule.get("id"), f"Missing id in {f.name}"
            assert rule.get("title"), f"Missing title in {f.name}"

    def test_real_rules_all_active(self):
        rules = list_rules(str(self._repo_root()))
        for r in rules:
            assert r["status"] == "active", f"Rule {r['id']} is not active: {r['status']}"
