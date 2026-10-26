"""Keyless model catalog used by `shux models update --catalog`.

Bindings name one model per tier, and providers release newer models often.
models.dev publishes one public JSON document, keyed by provider, that gives
every model a family and a release date. This module turns that document into
catalog entries and finds, for a bound model, the newest model of the same
provider and family. It never chooses across providers or families: a refresh
keeps the operator's choice of line and only moves it forward in time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class CatalogModel:
    id: str
    family: str
    release_date: date


def _parse_model(entry: Any) -> CatalogModel | None:
    """One catalog entry, or None when it lacks an id, a family or a valid date."""
    if not isinstance(entry, dict):
        return None
    model_id, family, released = entry.get("id"), entry.get("family"), entry.get("release_date")
    if not (isinstance(model_id, str) and isinstance(family, str) and isinstance(released, str)):
        return None
    try:
        release_date = date.fromisoformat(released)
    except ValueError:
        return None
    return CatalogModel(id=model_id, family=family, release_date=release_date)


def parse_catalog(data: Any) -> dict[str, list[CatalogModel]]:
    """Per-provider catalog entries from a models.dev document.

    Malformed providers and entries are skipped, never raised: a partial
    catalog still serves the providers it describes correctly.
    """
    catalog: dict[str, list[CatalogModel]] = {}
    if not isinstance(data, dict):
        return catalog
    for provider, body in data.items():
        if not isinstance(body, dict) or not isinstance(body.get("models"), dict):
            continue
        models = [m for m in map(_parse_model, body["models"].values()) if m is not None]
        if models:
            catalog[provider] = models
    return catalog


def newer_in_family(
    provider: str, bound_id: str, catalog: dict[str, list[CatalogModel]]
) -> CatalogModel | None:
    """The newest model of the bound model's provider and family released after it.

    Returns None when the bound model is not in the catalog (its family is
    unknown, so nothing can be proposed safely) or is already the newest.
    """
    models = catalog.get(provider, [])
    bound = next((m for m in models if m.id == bound_id), None)
    if bound is None:
        return None
    newer = [m for m in models if m.family == bound.family and m.release_date > bound.release_date]
    return max(newer, key=lambda m: (m.release_date, m.id), default=None)
