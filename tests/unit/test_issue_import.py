"""Iteration 3: issue_import — checklist parsing, field mapping, platform detection."""
from __future__ import annotations


def test_parse_checklist_extracts_unchecked_and_checked():
    from superharness.commands.issue_import import _parse_checklist

    body = "- [ ] a\n- [x] b\n"
    assert _parse_checklist(body) == ["a", "b"]


def test_issue_to_task_fields_maps_title_body_labels():
    from superharness.commands.issue_import import _issue_to_task_fields

    issue = {
        "title": "Fix the thing",
        "body": "Some context.\n- [ ] step one\n- [x] step two",
        "labels": [{"name": "bug"}],
    }
    fields = _issue_to_task_fields(issue, "https://github.com/o/r/issues/5")
    assert fields["title"] == "Fix the thing"
    assert fields["context"] == "Some context.\n- [ ] step one\n- [x] step two"
    assert fields["acceptance_criteria"] == ["step one", "step two"]
    assert fields["issue_url"] == "https://github.com/o/r/issues/5"


def test_platform_detection_github_vs_gitlab():
    from superharness.commands.issue_import import _detect_platform

    assert _detect_platform("https://github.com/o/r/issues/5") == "github"
    assert _detect_platform("https://gitlab.gs/o/r/-/issues/5") == "gitlab"
    assert _detect_platform("https://gitlab.com/o/r/-/issues/5") == "gitlab"


def test_body_with_no_checklist_yields_empty_criteria():
    from superharness.commands.issue_import import _issue_to_task_fields

    issue = {"title": "T", "body": "plain body, no checklist", "labels": []}
    fields = _issue_to_task_fields(issue, "https://github.com/o/r/issues/5")
    assert fields["acceptance_criteria"] == []
    assert fields["context"] == "plain body, no checklist"
