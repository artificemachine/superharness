"""ai_driven autonomy must enable plan auto-approval unless explicitly disabled."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from superharness.commands import task as task_cmd
from superharness.engine import tasks_dao
from superharness.engine.db import get_connection, init_db
from superharness.engine.profile import plan_auto_approval_enabled

_TASK_ID = "feat.default-plan-approval"


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ({}, True),
        # None is an explicit null document, not "no profile": callers pass {}
        # for a missing, empty or comment-only file.
        (None, False),
        ({"autonomy": "ai_driven"}, True),
        ({"autonomy": "full-auto"}, True),
        ({"autonomy": "supervised"}, False),
        ({"autonomy": "ai_driven", "auto_approve_plans": False}, False),
        ({"autonomy": "supervised", "auto_approve_plans": True}, True),
        ({"auto_approve_plans": False}, False),
        # Mistyped values are refused, never coerced: not even under ai_driven.
        ({"auto_approve_plans": "false"}, False),
        ({"auto_approve_plans": "true"}, False),
        ({"auto_approve_plans": "no"}, False),
        ({"autonomy": "ai_driven", "auto_approve_plans": "false"}, False),
        ({"auto_approve_plans": 1}, False),
        ({"auto_approve_plans": 0}, False),
        ({"auto_approve_plans": ["true"]}, False),
        ({"auto_approve_plans": True}, True),
        # A present key must hold a real boolean: null is not "absent".
        ({"auto_approve_plans": None}, False),
        ({"autonomy": "ai_driven", "auto_approve_plans": None}, False),
        # A profile root that is not a mapping is malformed, not "no profile".
        ("just text", False),
        (["a", "b"], False),
        ([], False),
        (0, False),
        ("", False),
    ],
)
def test_plan_auto_approval_enabled(profile, expected) -> None:
    assert plan_auto_approval_enabled(profile) is expected


def test_mistyped_plan_flag_is_not_logged_verbatim(caplog) -> None:
    with caplog.at_level("WARNING"):
        assert plan_auto_approval_enabled({"auto_approve_plans": "secret-xyz"}) is False

    assert "secret-xyz" not in caplog.text
    assert "auto_approve_plans" in caplog.text
    assert "str" in caplog.text


def _make_project(tmp_path: Path, profile_text: str | None) -> Path:
    harness = tmp_path / ".superharness"
    harness.mkdir(parents=True)
    if profile_text is not None:
        (harness / "profile.yaml").write_text(profile_text, encoding="utf-8")
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection(str(tmp_path))
    try:
        init_db(conn)
        tasks_dao.upsert(
            conn,
            tasks_dao.TaskRow(
                id=_TASK_ID,
                title="Default plan approval",
                owner="claude-code",
                status="in_progress",
                effort="low",
                project_path=str(tmp_path),
                development_method="tdd",
                acceptance_criteria=[],
                test_types=[],
                out_of_scope=[],
                definition_of_done=[],
                context="",
                tdd=None,
                version=1,
                created_at=now,
                updated_at=now,
                blocked_by=[],
                workflow="implementation",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return tmp_path


def _add_plan_handoff(project: Path, *, valid: bool = True) -> None:
    from superharness.engine import state_writer

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    tdd = {"red": "failing test", "green": "minimal code", "refactor": "none"}
    if not valid:
        del tdd["refactor"]
    assert state_writer.upsert_handoff(
        str(project),
        f"{_TASK_ID}-plan",
        {
            "task": _TASK_ID,
            "phase": "plan",
            "status": "plan_proposed",
            "from": "claude-code",
            "to": "owner",
            "date": now,
            "plan": "Add the default plan approval and test it.",
            "tdd": tdd,
            "risks": "No known risks.",
        },
    )


def _status_after_proposing(project: Path, monkeypatch) -> str:
    monkeypatch.setattr(task_cmd, "_enqueue_for_implementation", lambda *a, **k: None)
    task_cmd.status_update(str(project), _TASK_ID, "plan_proposed", actor="claude-code")
    conn = get_connection(str(project))
    try:
        init_db(conn)
        row = tasks_dao.get(conn, _TASK_ID)
        assert row is not None
        return row.status
    finally:
        conn.close()


def test_absent_profile_does_not_auto_approve(tmp_path: Path, monkeypatch) -> None:
    """No profile.yaml means nobody chose a policy: the operator approves."""
    project = _make_project(tmp_path, None)
    _add_plan_handoff(project)
    assert _status_after_proposing(project, monkeypatch) == "plan_proposed"


def test_valid_plan_is_auto_approved_for_ai_driven_profile(
    tmp_path: Path, monkeypatch
) -> None:
    project = _make_project(tmp_path, "autonomy: ai_driven\n")
    _add_plan_handoff(project)
    assert _status_after_proposing(project, monkeypatch) == "plan_approved"


@pytest.mark.parametrize("profile_text", [None, "autonomy: ai_driven\n"])
def test_missing_plan_handoff_blocks_auto_approval(
    tmp_path: Path, monkeypatch, profile_text
) -> None:
    project = _make_project(tmp_path, profile_text)
    assert _status_after_proposing(project, monkeypatch) == "plan_proposed"


@pytest.mark.parametrize(
    "profile_text",
    [
        'autonomy: ai_driven\nauto_approve_plans: "false"\n',
        'auto_approve_plans: "no"\n',
        "auto_approve_plans: 1\n",
        # Present but null, and roots that are not a mapping, are malformed.
        "auto_approve_plans:\n",
        "auto_approve_plans: null\n",
        "autonomy: ai_driven\nauto_approve_plans: ~\n",
        "- a\n- b\n",
        "just text\n",
        "0\n",
        "[]\n",
        # An explicit null document is not an empty file.
        "null\n",
        "~\n",
        "null # explicit\n",
        "---\n~\n",
    ],
)
def test_mistyped_flag_keeps_a_valid_plan_waiting_for_the_operator(
    tmp_path: Path, monkeypatch, profile_text
) -> None:
    project = _make_project(tmp_path, profile_text)
    _add_plan_handoff(project)
    assert _status_after_proposing(project, monkeypatch) == "plan_proposed"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", {}),
        ("# only a comment\n", {}),
        ("\n\n", {}),
        ("autonomy: ai_driven\n", {"autonomy": "ai_driven"}),
        ("null\n", None),
        ("~\n", None),
        ("- a\n", ["a"]),
    ],
)
def test_load_profile_document(tmp_path: Path, text, expected) -> None:
    from superharness.engine.profile import load_profile_document

    path = tmp_path / "profile.yaml"
    path.write_text(text, encoding="utf-8")
    assert load_profile_document(str(path)) == expected


def test_load_profile_document_rejects_a_multi_document_stream(tmp_path: Path) -> None:
    import yaml

    from superharness.engine.profile import load_profile_document

    path = tmp_path / "profile.yaml"
    path.write_text("a: 1\n---\nb: 2\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_profile_document(str(path))


@pytest.mark.parametrize("profile_text", ["", "# only a comment\n"])
def test_an_empty_profile_file_keeps_the_default(
    tmp_path: Path, monkeypatch, profile_text
) -> None:
    project = _make_project(tmp_path, profile_text)
    _add_plan_handoff(project)
    assert _status_after_proposing(project, monkeypatch) == "plan_approved"


def test_invalid_plan_blocks_auto_approval(tmp_path: Path, monkeypatch) -> None:
    project = _make_project(tmp_path, None)
    _add_plan_handoff(project, valid=False)
    assert _status_after_proposing(project, monkeypatch) == "plan_proposed"


@pytest.mark.parametrize("error", [RuntimeError("boom"), ImportError("no validator")])
def test_validator_failure_blocks_auto_approval(
    tmp_path: Path, monkeypatch, error
) -> None:
    from superharness.engine import plan_validator

    def raising_validator(plan, contract_task):
        raise error

    project = _make_project(tmp_path, None)
    _add_plan_handoff(project)
    monkeypatch.setattr(plan_validator, "validate_plan", raising_validator)
    assert _status_after_proposing(project, monkeypatch) == "plan_proposed"


def test_explicit_false_keeps_plan_waiting_for_the_operator(
    tmp_path: Path, monkeypatch
) -> None:
    project = _make_project(tmp_path, "autonomy: ai_driven\nauto_approve_plans: false\n")
    assert _status_after_proposing(project, monkeypatch) == "plan_proposed"


def test_supervised_autonomy_keeps_plan_waiting_for_the_operator(
    tmp_path: Path, monkeypatch
) -> None:
    project = _make_project(tmp_path, "autonomy: supervised\n")
    assert _status_after_proposing(project, monkeypatch) == "plan_proposed"


@pytest.mark.parametrize(
    ("profile_text", "reaches_task_scan"),
    [
        (None, True),
        ("autonomy: ai_driven\n", True),
        ("autonomy: ai_driven\nauto_approve_plans: false\n", False),
        ("autonomy: supervised\n", False),
        ("", True),
        ("# only a comment\n", True),
        ("auto_approve_plans: null\n", False),
        ("- a\n- b\n", False),
        ("0\n", False),
        ("null\n", False),
        ("~\n", False),
    ],
)
def test_peer_plan_review_gate_follows_default_autonomy(
    tmp_path: Path, monkeypatch, profile_text, reaches_task_scan
) -> None:
    from superharness.commands import inbox_watch

    project = _make_project(tmp_path, profile_text)
    scanned: list[str] = []

    def fake_load_tasks(project_dir: str) -> list:
        scanned.append(project_dir)
        return []

    monkeypatch.setattr(inbox_watch, "_load_tasks", fake_load_tasks)

    assert inbox_watch._auto_peer_approve_plans(str(project)) == 0
    assert bool(scanned) is reaches_task_scan
