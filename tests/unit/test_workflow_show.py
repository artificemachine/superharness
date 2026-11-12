"""`shux workflow --show` reports whether plans are auto-approved, and why."""

from __future__ import annotations

import json
from pathlib import Path

# Reuse the subprocess helpers of the sibling workflow CLI tests.
from test_workflow_cmd import (  # type: ignore[import-not-found]
    _make_project,
    _run_workflow,
)


def _show(project: Path) -> dict:
    r = _run_workflow(project, "--show", "--json")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_show_reports_plan_auto_approval_source(tmp_path: Path) -> None:
    absent = _show(_make_project(tmp_path / "a", profile=None))
    assert absent["plan_auto_approval"]["enabled"] is False
    assert "profile=absent" in absent["plan_auto_approval"]["source"]

    explicit = _show(
        _make_project(tmp_path / "b", profile={"auto_approve_plans": False})
    )
    assert explicit["plan_auto_approval"]["enabled"] is False
    assert "profile=explicit" in explicit["plan_auto_approval"]["source"]


def test_show_keeps_every_existing_key(tmp_path: Path) -> None:
    data = _show(_make_project(tmp_path, profile={"autonomy": "supervised"}))
    assert data["autonomy"] == "supervised"
    assert set(data["workflow"]) == {"default_preset", "require_tdd"}
    assert data["workflow"]["default_preset"] == "implementation"
    assert data["workflow"]["require_tdd"] is True


def test_show_malformed_profile_reports_disabled(tmp_path: Path) -> None:
    project = _make_project(tmp_path, profile=None)
    (project / ".superharness" / "profile.yaml").write_text("- a\n- b\n")
    r = _run_workflow(project, "--show", "--json")
    # An unreadable-as-mapping profile must not crash the report.
    data = json.loads(r.stdout)
    assert data["plan_auto_approval"]["enabled"] is False
    assert "profile=malformed" in data["plan_auto_approval"]["source"]
