"""Keyless model catalog used by `shux models update --catalog`.

Bindings name one model per tier, and providers release newer models often.
models.dev publishes one public JSON document, keyed by provider, that gives
every model a family and a release date. This module turns that document into
catalog entries and finds, for a bound model, the newest model of the same
provider and family. It never chooses across providers or families: a refresh
keeps the operator's choice of line and only moves it forward in time.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

MODELS_DEV_URL = "https://models.dev/api.json"
CATALOG_URL_ENV = "SUPERHARNESS_MODELS_CATALOG_URL"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_BYTES = 16 * 1024 * 1024
_USER_AGENT = "superharness-models-catalog"

Opener = Callable[..., Any]


@dataclass(frozen=True)
class CatalogModel:
    id: str
    family: str
    release_date: date


@dataclass(frozen=True)
class CatalogFailure:
    """Why a catalog or docs page could not be read; never an exception."""

    source: str
    reason: str


def _read_capped(response: Any, max_bytes: int) -> bytes | None:
    """The response body, or None when it is larger than ``max_bytes``."""
    body = response.read(max_bytes + 1)
    return None if len(body) > max_bytes else body


def _fetch_bytes(
    url: str, source: str, *, timeout: float, max_bytes: int, opener: Opener
) -> bytes | CatalogFailure:
    """GET ``url`` without credentials; a network or size problem is a failure value."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with opener(request, timeout=timeout) as response:
            body = _read_capped(response, max_bytes)
    except urllib.error.HTTPError as exc:
        return CatalogFailure(source, f"HTTP {exc.code} from {url}")
    except urllib.error.URLError as exc:
        return CatalogFailure(source, f"cannot reach {url}: {exc.reason}")
    except (TimeoutError, OSError) as exc:
        return CatalogFailure(source, f"cannot read {url}: {exc}")
    if body is None:
        return CatalogFailure(source, f"response from {url} is larger than {max_bytes} bytes")
    return body


def fetch_catalog(
    url: str | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    opener: Opener = urllib.request.urlopen,
) -> dict[str, list[CatalogModel]] | CatalogFailure:
    """Download and parse the models.dev catalog; return a failure value instead of raising.

    ``SUPERHARNESS_MODELS_CATALOG_URL`` overrides the address, for a mirror or
    a test server. A document that parses to no model at all is a failure,
    so an empty or reshaped catalog never reads as "nothing newer".
    """
    target = url or os.environ.get(CATALOG_URL_ENV) or MODELS_DEV_URL
    body = _fetch_bytes(target, "models.dev", timeout=timeout, max_bytes=max_bytes, opener=opener)
    if isinstance(body, CatalogFailure):
        return body
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return CatalogFailure("models.dev", f"invalid JSON from {target}: {exc}")
    catalog = parse_catalog(data)
    if not catalog:
        return CatalogFailure("models.dev", f"no models with a family and release date in {target}")
    return catalog


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
