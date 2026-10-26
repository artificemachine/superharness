"""Tests for the keyless model catalog (models.dev) used by `shux models update --catalog`."""

from __future__ import annotations

import json
import urllib.error
from datetime import date
from typing import Self

from superharness.engine.model_catalog import (
    CatalogFailure,
    CatalogModel,
    DocsCheck,
    DocsChecker,
    fetch_catalog,
    newer_in_family,
    parse_catalog,
)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _opener_returning(body: bytes, seen: list[str] | None = None):
    def opener(request, timeout):
        if seen is not None:
            seen.append(request.full_url)
        return _FakeResponse(body)

    return opener


def _opener_raising(exc: BaseException):
    def opener(request, timeout):
        raise exc

    return opener

SAMPLE = {
    "anthropic": {
        "id": "anthropic",
        "models": {
            "claude-haiku-4-5": {"id": "claude-haiku-4-5", "family": "claude-haiku",
                                 "release_date": "2025-10-15"},
            "claude-haiku-5-5": {"id": "claude-haiku-5-5", "family": "claude-haiku",
                                 "release_date": "2026-10-07"},
            "claude-opus-5-5": {"id": "claude-opus-5-5", "family": "claude-opus",
                                "release_date": "2026-09-22"},
        },
    },
    "openai": {
        "id": "openai",
        "models": {
            "gpt-5.6-sol": {"id": "gpt-5.6-sol", "family": "gpt-sol", "release_date": "2026-07-09"},
            "gpt-6.1-sol": {"id": "gpt-6.1-sol", "family": "gpt-sol", "release_date": "2026-09-29"},
        },
    },
}


def test_parse_catalog_keeps_family_and_release_date():
    catalog = parse_catalog(SAMPLE)

    assert set(catalog) == {"anthropic", "openai"}
    haiku = {m.id: m for m in catalog["anthropic"]}["claude-haiku-5-5"]
    assert haiku == CatalogModel(id="claude-haiku-5-5", family="claude-haiku",
                                 release_date=date(2026, 10, 7))


def test_newer_in_family_picks_latest_release():
    catalog = parse_catalog(SAMPLE)

    newer = newer_in_family("anthropic", "claude-haiku-4-5", catalog)
    assert newer is not None and newer.id == "claude-haiku-5-5"
    newer = newer_in_family("openai", "gpt-5.6-sol", catalog)
    assert newer is not None and newer.id == "gpt-6.1-sol"


def test_newer_in_family_ignores_other_families():
    catalog = parse_catalog(SAMPLE)

    # claude-opus-5-5 is newer than haiku 4.5 but belongs to another family.
    newer = newer_in_family("anthropic", "claude-haiku-4-5", catalog)
    assert newer is not None and newer.family == "claude-haiku"


def test_newer_in_family_none_when_bound_is_latest_or_unknown():
    catalog = parse_catalog(SAMPLE)

    assert newer_in_family("anthropic", "claude-haiku-5-5", catalog) is None
    assert newer_in_family("anthropic", "claude-not-in-catalog", catalog) is None
    assert newer_in_family("deepseek", "deepseek-flash", catalog) is None


def test_parse_catalog_rejects_malformed_input():
    assert parse_catalog(["not", "an", "object"]) == {}
    assert parse_catalog({"anthropic": "not a provider"}) == {}
    catalog = parse_catalog({
        "anthropic": {"models": {
            "no-family": {"id": "no-family", "release_date": "2026-01-01"},
            "no-date": {"id": "no-date", "family": "claude-haiku"},
            "bad-date": {"id": "bad-date", "family": "claude-haiku", "release_date": "soon"},
            "ok": {"id": "ok", "family": "claude-haiku", "release_date": "2026-01-01"},
        }},
    })
    assert [m.id for m in catalog["anthropic"]] == ["ok"]


def test_fetch_catalog_parses_a_served_document(monkeypatch):
    seen: list[str] = []
    monkeypatch.setenv("SUPERHARNESS_MODELS_CATALOG_URL", "https://mirror.example/api.json")

    result = fetch_catalog(opener=_opener_returning(json.dumps(SAMPLE).encode(), seen))

    assert seen == ["https://mirror.example/api.json"]
    assert isinstance(result, dict)
    assert {m.id for m in result["openai"]} == {"gpt-5.6-sol", "gpt-6.1-sol"}


def test_fetch_catalog_reports_timeout_and_http_errors():
    url = "https://models.dev/api.json"
    failures = [
        fetch_catalog(opener=_opener_raising(urllib.error.URLError("no route to host"))),
        fetch_catalog(opener=_opener_raising(TimeoutError("timed out"))),
        fetch_catalog(opener=_opener_raising(
            urllib.error.HTTPError(url, 500, "Server Error", hdrs=None, fp=None))),
    ]

    for failure in failures:
        assert isinstance(failure, CatalogFailure)
        assert failure.source == "models.dev"
    assert "no route to host" in failures[0].reason
    assert "timed out" in failures[1].reason
    assert "HTTP 500" in failures[2].reason


def test_fetch_catalog_rejects_oversized_or_invalid_json():
    oversized = fetch_catalog(opener=_opener_returning(b"x" * 11), max_bytes=10)
    invalid = fetch_catalog(opener=_opener_returning(b"{not json"))
    empty = fetch_catalog(opener=_opener_returning(b"{}"))

    assert isinstance(oversized, CatalogFailure) and "larger than" in oversized.reason
    assert isinstance(invalid, CatalogFailure) and "invalid JSON" in invalid.reason
    assert isinstance(empty, CatalogFailure) and "no models" in empty.reason


def test_docs_mentions_confirms_an_id_present_in_the_page():
    page = b"<html><td><code>gpt-6.1-sol</code></td><td>gpt-6-sol-mini</td></html>"
    checker = DocsChecker(opener=_opener_returning(page))

    assert checker.check("openai", "gpt-6.1-sol") == DocsCheck("confirmed")
    # gpt-6-sol only appears as part of a longer id, so it is not confirmed.
    assert checker.check("openai", "gpt-6-sol").status == "absent"
    # gpt-6 must not match inside gpt-6.1-sol.
    assert checker.check("openai", "gpt-6").status == "absent"


def test_docs_mentions_absent_and_unreachable():
    calls: list[str] = []
    checker = DocsChecker(opener=_opener_returning(b"<p>claude-opus-5-5</p>", calls))
    assert checker.check("anthropic", "claude-haiku-5-5") == DocsCheck("absent")
    assert checker.check("anthropic", "claude-opus-5-5") == DocsCheck("confirmed")
    assert len(calls) == 1  # one fetch per page per run

    down = DocsChecker(opener=_opener_raising(urllib.error.URLError("dns failure")))
    result = down.check("anthropic", "claude-opus-5-5")
    assert result.status == "unreachable"
    assert "dns failure" in result.reason


def test_docs_mentions_not_applicable_for_other_providers():
    calls: list[str] = []
    checker = DocsChecker(opener=_opener_returning(b"", calls))

    assert checker.check("deepseek", "deepseek-flash").status == "not-applicable"
    assert checker.check("zai-coding-plan", "glm-5.3").status == "not-applicable"
    assert calls == []
