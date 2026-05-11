"""Tests for superharness.utils.privacy.strip_private_tags.

The utility removes <private>...</private> spans from agent-authored text
before it lands in SQLite. Borrowed pattern from claude-mem with applied
at the superharness write boundary instead of a hook layer.
"""
from __future__ import annotations

import pytest

from superharness.utils.privacy import strip_private_tags, PRIVATE_TAG_RE


def test_strip_single_span():
    assert strip_private_tags("before <private>secret</private> after") == "before  after"


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
