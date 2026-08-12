"""Tests for superharness.utils.privacy.strip_private_tags.

The utility removes <private>...</private> spans from agent-authored text
before it lands in SQLite. Borrowed pattern from claude-mem with applied
at the superharness write boundary instead of a hook layer.
"""

from __future__ import annotations

import pytest

from superharness.engine import decisions_dao, failures_dao, handoffs_dao
from superharness.utils.privacy import strip_private_tags, PRIVATE_TAG_RE


T0 = "2026-01-01T00:00:00Z"


@pytest.fixture
def privacy_db(tmp_path):
    from superharness.engine.db import get_connection, init_db

    (tmp_path / ".superharness").mkdir()
    conn = get_connection(str(tmp_path))
    init_db(conn)
    yield conn
    conn.close()


def test_strip_single_span():
    assert (
        strip_private_tags("before <private>secret</private> after") == "before  after"
    )


def test_strip_multiple_spans():
    text = "a <private>x</private> b <private>y</private> c"
    assert strip_private_tags(text) == "a  b  c"


def test_strip_multiline_span():
    text = "head\n<private>line1\nline2\nline3</private>\ntail"
    assert strip_private_tags(text) == "head\n\ntail"


def test_no_tags_passes_through():
    assert strip_private_tags("nothing to strip") == "nothing to strip"


def test_unmatched_open_tag_left_alone():
    text = "open <private> but no close"
    assert strip_private_tags(text) == text


def test_unmatched_close_tag_left_alone():
    text = "no open </private> only close"
    assert strip_private_tags(text) == text


def test_empty_string_returns_empty():
    assert strip_private_tags("") == ""


def test_none_returns_empty():
    assert strip_private_tags(None) == ""


def test_idempotent():
    text = "x <private>a</private> y <private>b</private> z"
    once = strip_private_tags(text)
    twice = strip_private_tags(once)
    assert once == twice


def test_non_greedy_matching():
    text = "<private>a</private>middle<private>b</private>"
    assert strip_private_tags(text) == "middle"


def test_compiled_regex_constant_available():
    assert PRIVATE_TAG_RE.search("<private>x</private>") is not None
    assert PRIVATE_TAG_RE.search("no tags here") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("<private></private>", ""),
        ("a<private></private>b", "ab"),
        ("<private>only</private>", ""),
    ],
)
def test_empty_and_boundary_spans(text, expected):
    assert strip_private_tags(text) == expected


def test_handoff_dao_strips_private_tags_from_content_and_nested_metadata(privacy_db):
    privacy_db.execute(
        "INSERT INTO tasks (id, title, status, version, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("privacy-handoff", "Privacy", "todo", 1, T0),
    )

    row = handoffs_dao.append(
        privacy_db,
        task_id="privacy-handoff",
        phase="report",
        status="report_ready",
        content="visible <private>handoff secret</private> text",
        metadata={
            "note": "keep <private>metadata secret</private> safe",
            "nested": {"items": ["<private>token</private>visible", 7]},
        },
        now=T0,
    )

    assert row.content == "visible  text"
    assert row.metadata == {
        "note": "keep  safe",
        "nested": {"items": ["visible", 7]},
    }


def test_decision_dao_strips_private_tags_from_all_authored_fields(privacy_db):
    row = decisions_dao.record(
        privacy_db,
        decision="choose <private>secret option</private> SQLite",
        reason="because <private>private rationale</private> durable",
        alternatives=[
            "YAML <private>credential</private>",
            "<private>hidden</private>files",
        ],
        now=T0,
    )

    assert row.decision == "choose  SQLite"
    assert row.reason == "because  durable"
    assert row.alternatives == ["YAML ", "files"]


def test_failure_dao_strips_private_tags_from_all_authored_fields(privacy_db):
    row = failures_dao.record(
        privacy_db,
        pattern="auth <private>private pattern</private> failure",
        error_snippet="before <private>raw credential</private> after",
        now=T0,
    )

    assert row.pattern == "auth  failure"
    assert row.error_snippet == "before  after"
