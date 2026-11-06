"""auto_close in profile.yaml is a strict boolean, like auto_approve_plans.

A mistyped value must never turn the watcher's auto-close on: ``auto_close:
"false"`` is a non-empty string and used to be truthy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from superharness.commands import inbox_watch
from superharness.engine.profile import auto_close_enabled


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ({}, True),
        (None, False),
        ([], False),
        ({"autonomy": "ai_driven"}, True),
        ({"autonomy": "supervised"}, False),
        ({"auto_close": True}, True),
        ({"auto_close": False}, False),
        ({"autonomy": "supervised", "auto_close": True}, True),
        ({"autonomy": "ai_driven", "auto_close": False}, False),
        # Mistyped values are refused, never coerced: not even under ai_driven.
        ({"auto_close": "false"}, False),
        ({"auto_close": "true"}, False),
        ({"auto_close": "no"}, False),
        ({"auto_close": 1}, False),
        ({"auto_close": 0}, False),
        ({"auto_close": None}, False),
        ({"auto_close": ["true"]}, False),
    ],
)
def test_auto_close_enabled(profile: object, expected: bool) -> None:
    assert auto_close_enabled(profile) is expected


def _write_profile(project: Path, text: str) -> None:
    sh = project / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    (sh / "profile.yaml").write_text(text, encoding="utf-8")


@pytest.fixture
def load_tasks_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record whether the watcher got past the auto_close gate."""
    calls: list[str] = []

    def fake_load_tasks(project_dir: str) -> list[dict]:
        calls.append(project_dir)
        return []

    monkeypatch.setattr(inbox_watch, "_load_tasks", fake_load_tasks)
    return calls


@pytest.mark.parametrize(
    "func_name", ["_auto_close_report_ready", "_auto_close_review_passed"]
)
@pytest.mark.parametrize(
    ("profile_text", "passes_gate"),
    [
        ("auto_close: true\n", True),
        ("autonomy: ai_driven\n", True),
        ("", True),
        ("auto_close: false\n", False),
        ("autonomy: supervised\n", False),
        ('auto_close: "false"\n', False),
        ('autonomy: ai_driven\nauto_close: "no"\n', False),
        ("auto_close: 1\n", False),
        ("auto_close:\n", False),
        ("~\n", False),
        ("- auto_close\n", False),
    ],
)
def test_watcher_gate_requires_a_real_boolean(
    tmp_path: Path,
    load_tasks_calls: list[str],
    func_name: str,
    profile_text: str,
    passes_gate: bool,
) -> None:
    _write_profile(tmp_path, profile_text)

    getattr(inbox_watch, func_name)(str(tmp_path))

    assert bool(load_tasks_calls) is passes_gate


@pytest.mark.parametrize(
    "func_name", ["_auto_close_report_ready", "_auto_close_review_passed"]
)
def test_watcher_gate_without_profile_follows_default_autonomy(
    tmp_path: Path, load_tasks_calls: list[str], func_name: str
) -> None:
    getattr(inbox_watch, func_name)(str(tmp_path))

    assert load_tasks_calls == [str(tmp_path)]
