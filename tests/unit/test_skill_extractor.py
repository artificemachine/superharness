"""Tests for superharness.engine.skill_extractor."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def _make_task(**kwargs) -> dict:
    base = {
        "id": "feat.test-task",
        "title": "Add YAML config parser",
        "owner": "claude-code",
        "status": "done",
        "summary": "Implemented a YAML config parser with validation.",
        "acceptance_criteria": ["parser reads config.yaml", "invalid keys raise ValueError"],
        "tdd": {
            "red": "write failing test for parse()",
            "green": "implement parse() to pass",
            "refactor": "extract _validate() helper",
        },
    }
    base.update(kwargs)
    return base


class TestCategoryInference:
    def test_infers_test_from_keywords(self) -> None:
        from superharness.engine.skill_extractor import _infer_category
        assert _infer_category("write pytest fixtures and mock database") == "test"

    def test_infers_bug_fix(self) -> None:
        from superharness.engine.skill_extractor import _infer_category
        assert _infer_category("fix crash in parser when key is missing") == "bug-fix"

    def test_infers_refactor(self) -> None:
        from superharness.engine.skill_extractor import _infer_category
        assert _infer_category("refactor delegate into smaller helpers") == "refactor"

    def test_infers_feature_as_default(self) -> None:
        from superharness.engine.skill_extractor import _infer_category
        assert _infer_category("implement new workflow engine") == "feature"

    def test_infers_docs(self) -> None:
        from superharness.engine.skill_extractor import _infer_category
        assert _infer_category("update README and add docstrings") == "docs"

    def test_infers_security(self) -> None:
        from superharness.engine.skill_extractor import _infer_category
        assert _infer_category("rotate API secret and enforce auth check") == "security"


class TestTechniqueExtraction:
    def test_extracts_known_techniques(self) -> None:
        from superharness.engine.skill_extractor import _extract_techniques
        text = "use dataclass decorator with threading and pathlib"
        techniques = _extract_techniques(text)
        assert "dataclass" in techniques
        assert "threading" in techniques
        assert "pathlib" in techniques

    def test_caps_at_eight(self) -> None:
        from superharness.engine.skill_extractor import _extract_techniques
        text = "dataclass decorator threading pathlib argparse generator async middleware hook observer registry"
        techniques = _extract_techniques(text)
        assert len(techniques) <= 8

    def test_empty_text_returns_empty(self) -> None:
        from superharness.engine.skill_extractor import _extract_techniques
        assert _extract_techniques("") == []


class TestExtractSkillFromTask:
    def test_basic_extraction(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import extract_skill_from_task
        task = _make_task()
        with patch("superharness.engine.skill_extractor._get_diff_summary", return_value={
            "files_changed": 3, "insertions": 50, "deletions": 5,
            "file_types": [".py"], "test_files_changed": True,
        }):
            skill = extract_skill_from_task(str(tmp_path), task)

        assert skill is not None
        assert skill.task_id == "feat.test-task"
        assert skill.title == "Add YAML config parser"
        assert skill.tdd_used is True
        assert skill.test_coverage is True
        assert skill.files_changed == 3

    def test_tdd_detected_from_tdd_block(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import extract_skill_from_task
        task = _make_task()
        with patch("superharness.engine.skill_extractor._get_diff_summary", return_value={
            "files_changed": 0, "insertions": 0, "deletions": 0,
            "file_types": [], "test_files_changed": False,
        }):
            skill = extract_skill_from_task(str(tmp_path), task)
        assert skill is not None
        assert skill.tdd_used is True

    def test_no_tdd_when_missing(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import extract_skill_from_task
        task = _make_task(tdd={})
        with patch("superharness.engine.skill_extractor._get_diff_summary", return_value={
            "files_changed": 0, "insertions": 0, "deletions": 0,
            "file_types": [], "test_files_changed": False,
        }):
            skill = extract_skill_from_task(str(tmp_path), task)
        assert skill is not None
        assert skill.tdd_used is False

    def test_returns_none_for_empty_task(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import extract_skill_from_task
        skill = extract_skill_from_task(str(tmp_path), {})
        assert skill is None

    def test_category_derived_from_corpus(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import extract_skill_from_task
        # No TDD block so TDD text doesn't influence category detection
        task = _make_task(title="Fix crash on empty input", summary="fixed a bug causing crash", tdd={})
        with patch("superharness.engine.skill_extractor._get_diff_summary", return_value={
            "files_changed": 1, "insertions": 10, "deletions": 2,
            "file_types": [".py"], "test_files_changed": False,
        }):
            skill = extract_skill_from_task(str(tmp_path), task)
        assert skill is not None
        assert skill.category == "bug-fix"


class TestRecordSkill:
    def test_writes_to_skills_yaml(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import record_skill, _load_skills
        (tmp_path / ".superharness").mkdir()
        task = _make_task()
        with patch("superharness.engine.skill_extractor._get_diff_summary", return_value={
            "files_changed": 2, "insertions": 20, "deletions": 3,
            "file_types": [".py"], "test_files_changed": True,
        }):
            skill = record_skill(str(tmp_path), task)

        assert skill is not None
        data = _load_skills(str(tmp_path / ".superharness" / "skills.yaml"))
        assert len(data["skills"]) == 1
        assert data["skills"][0]["task_id"] == "feat.test-task"

    def test_no_duplicates_same_task_id(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import record_skill, _load_skills
        (tmp_path / ".superharness").mkdir()
        task = _make_task()
        with patch("superharness.engine.skill_extractor._get_diff_summary", return_value={
            "files_changed": 1, "insertions": 10, "deletions": 0,
            "file_types": [".py"], "test_files_changed": False,
        }):
            record_skill(str(tmp_path), task)
            record_skill(str(tmp_path), task)  # second call same task_id

        data = _load_skills(str(tmp_path / ".superharness" / "skills.yaml"))
        assert len(data["skills"]) == 1

    def test_different_tasks_both_recorded(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import record_skill, _load_skills
        (tmp_path / ".superharness").mkdir()
        with patch("superharness.engine.skill_extractor._get_diff_summary", return_value={
            "files_changed": 1, "insertions": 10, "deletions": 0,
            "file_types": [".py"], "test_files_changed": False,
        }):
            record_skill(str(tmp_path), _make_task(id="feat.a", title="Task A"))
            record_skill(str(tmp_path), _make_task(id="feat.b", title="Task B"))

        data = _load_skills(str(tmp_path / ".superharness" / "skills.yaml"))
        assert len(data["skills"]) == 2


class TestSearchSkills:
    def _populate(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import record_skill
        (tmp_path / ".superharness").mkdir()
        with patch("superharness.engine.skill_extractor._get_diff_summary", return_value={
            "files_changed": 1, "insertions": 10, "deletions": 0,
            "file_types": [".py"], "test_files_changed": False,
        }):
            record_skill(str(tmp_path), _make_task(id="feat.yaml-parser", title="YAML config parser",
                         summary="Parses YAML config with validation"))
            record_skill(str(tmp_path), _make_task(id="feat.sdk-runner", title="SDK dispatch runner",
                         summary="Runs SDK dispatch with threading"))
            record_skill(str(tmp_path), _make_task(id="fix.inbox-lock", title="Fix inbox lock contention",
                         summary="Fixed mutex lock in inbox dispatch",
                         tdd={}))

    def test_keyword_match_returns_results(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import search_skills
        self._populate(tmp_path)
        results = search_skills(str(tmp_path), "yaml config")
        assert len(results) >= 1
        assert any("yaml" in r.get("title", "").lower() or "yaml" in r.get("summary", "").lower()
                   for r in results)

    def test_no_match_returns_empty(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import search_skills
        self._populate(tmp_path)
        results = search_skills(str(tmp_path), "completely unrelated zxzxzxzx")
        assert results == []

    def test_top_n_respected(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import search_skills
        self._populate(tmp_path)
        # "dispatch runner lock" should match sdk-runner and inbox-lock
        results = search_skills(str(tmp_path), "dispatch lock inbox", top_n=1)
        assert len(results) <= 1


class TestGetSkillHints:
    def test_returns_hints_for_related_task(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import record_skill, get_skill_hints
        (tmp_path / ".superharness").mkdir()
        with patch("superharness.engine.skill_extractor._get_diff_summary", return_value={
            "files_changed": 2, "insertions": 20, "deletions": 0,
            "file_types": [".py"], "test_files_changed": True,
        }):
            record_skill(str(tmp_path), _make_task(id="feat.yaml-cfg", title="YAML config loader",
                         summary="Loads and validates YAML config"))

        hints = get_skill_hints(str(tmp_path), {
            "title": "YAML settings parser",
            "acceptance_criteria": ["parses yaml settings"],
        })
        assert len(hints) >= 1
        assert any("YAML" in h or "yaml" in h.lower() for h in hints)

    def test_returns_empty_for_unrelated_task(self, tmp_path: Path) -> None:
        from superharness.engine.skill_extractor import record_skill, get_skill_hints
        (tmp_path / ".superharness").mkdir()
        with patch("superharness.engine.skill_extractor._get_diff_summary", return_value={
            "files_changed": 1, "insertions": 5, "deletions": 0,
            "file_types": [".py"], "test_files_changed": False,
        }):
            record_skill(str(tmp_path), _make_task(id="feat.yaml-cfg", title="YAML config",
                         summary="Config loader"))

        hints = get_skill_hints(str(tmp_path), {"title": "Kubernetes network policy"})
        assert hints == []
