"""Tests for the keyless model catalog (models.dev) used by `shux models update --catalog`."""

from __future__ import annotations

from datetime import date

from superharness.engine.model_catalog import (
    CatalogModel,
    newer_in_family,
    parse_catalog,
)

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
