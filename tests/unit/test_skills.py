"""Tests for skills loader (cherry-picked from hermes-agent)."""
import pytest
from superharness.skills.loader import save_skill, load_skill, discover_skills, list_skill_names, delete_skill


class TestSkills:
    def test_save_and_load_skill(self, tmp_path):
        skill = {"name": "deploy-staging", "description": "Deploy to staging",
                 "tags": ["deploy", "ci"], "steps": [{"run": "git push"}]}
        ok = save_skill(str(tmp_path), "deploy-staging", skill)
        assert ok is True
        loaded = load_skill(str(tmp_path), "deploy-staging")
        assert loaded["name"] == "deploy-staging"
        assert loaded["tags"] == ["deploy", "ci"]

    def test_load_nonexistent_skill(self, tmp_path):
        assert load_skill(str(tmp_path), "nonexistent") is None

    def test_discover_by_tag(self, tmp_path):
        save_skill(str(tmp_path), "deploy", {"name": "deploy", "tags": ["deploy", "ci"]})
        save_skill(str(tmp_path), "format", {"name": "format", "tags": ["style"]})
        results = discover_skills(str(tmp_path), tags=["deploy"])
        assert len(results) == 1
        assert results[0]["name"] == "deploy"

    def test_list_all_skills(self, tmp_path):
        save_skill(str(tmp_path), "a", {"name": "a"})
        save_skill(str(tmp_path), "b", {"name": "b"})
        names = list_skill_names(str(tmp_path))
        assert "a" in names
        assert "b" in names

    def test_delete_skill(self, tmp_path):
        save_skill(str(tmp_path), "temp", {"name": "temp"})
        assert delete_skill(str(tmp_path), "temp") is True
        assert load_skill(str(tmp_path), "temp") is None

    def test_discover_no_tags_returns_all(self, tmp_path):
        save_skill(str(tmp_path), "x", {"name": "x", "tags": ["a"]})
        save_skill(str(tmp_path), "y", {"name": "y", "tags": ["b"]})
        assert len(discover_skills(str(tmp_path))) == 2

    def test_empty_skills_dir(self, tmp_path):
        assert list_skill_names(str(tmp_path)) == []
