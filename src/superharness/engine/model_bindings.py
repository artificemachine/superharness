"""superharness's own model bindings file: load, ladder, freshness.

The bindings file (schema 2) is the single place where a tier becomes a model
id. It lives in superharness's config directory; this module only reads it.
Every function here is pure apart from the one file read in
:func:`load_bindings`, and none of them raises on bad content: problems are
reported through :class:`BindingsFile.status` and ``reason``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 2

# Dispatch tiers used across superharness, mapped to the bindings tiers.
DISPATCH_TO_BINDING_TIER = {
    "mini": "bulk",
    "standard": "default",
    "max": "escalate-1",
}

# Ladder order used when the file omits its own `tiers:` list.
DEFAULT_LADDER_ORDER = ("bulk", "default", "escalate-1", "escalate-2", "final-review")

DEFAULT_REVIEW_AFTER_DAYS = 5


@dataclass(frozen=True)
class BindingsFile:
    """A loaded bindings file: ``status`` is ``ok``, ``missing`` or ``invalid``."""

    path: Path
    status: str
    reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def load_bindings(path: Path) -> BindingsFile:
    """Read and validate the bindings file at ``path``."""
    if not path.exists():
        return BindingsFile(path, "missing", f"no bindings file at {path}")
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as exc:
        return BindingsFile(path, "invalid", f"cannot read {path}: {exc}")
    except yaml.YAMLError as exc:
        return BindingsFile(path, "invalid", f"invalid YAML in {path}: {exc}")
    if not isinstance(data, dict):
        return BindingsFile(path, "invalid", "the file must be a YAML mapping")
    if data.get("schema") != SCHEMA_VERSION:
        return BindingsFile(
            path, "invalid", f"unsupported schema {data.get('schema')!r}; expected {SCHEMA_VERSION}"
        )
    return BindingsFile(path, "ok", data=data)


def _harness(bindings: BindingsFile, harness: str) -> dict[str, Any] | None:
    harnesses = bindings.data.get("harnesses")
    entry = harnesses.get(harness) if isinstance(harnesses, dict) else None
    return entry if isinstance(entry, dict) else None


def _model_id(provider_bindings: dict[str, Any], binding_tier: str) -> str | None:
    binding = provider_bindings.get(binding_tier)
    if not isinstance(binding, dict):
        return None
    model_id = binding.get("id")
    return model_id.strip() if isinstance(model_id, str) and model_id.strip() else None


def provider_ladder(bindings: BindingsFile, harness: str, binding_tier: str) -> list[str]:
    """Return the model bound to ``binding_tier``, then the rest of its provider's ladder.

    A tier resolves inside the harness's default provider only, never across
    providers. Fallbacks come from higher tiers first, then lower ones. An
    empty list means the tier has no binding for this harness.
    """
    entry = _harness(bindings, harness)
    if entry is None:
        return []
    provider = entry.get("default_provider")
    all_bindings = entry.get("bindings")
    if not isinstance(provider, str) or not provider or not isinstance(all_bindings, dict):
        return []
    provider_bindings = all_bindings.get(provider)
    if not isinstance(provider_bindings, dict):
        return []

    bound = _model_id(provider_bindings, binding_tier)
    if bound is None:
        return []

    order = bindings.data.get("tiers")
    if not isinstance(order, list) or binding_tier not in order:
        order = list(DEFAULT_LADDER_ORDER)
    position = order.index(binding_tier)
    fallback_tiers = order[position + 1 :] + list(reversed(order[:position]))

    ladder = [bound]
    for fallback_tier in fallback_tiers:
        model_id = _model_id(provider_bindings, str(fallback_tier))
        if model_id and model_id not in ladder:
            ladder.append(model_id)
    return ladder


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def stale_providers(bindings: BindingsFile, today: date) -> list[str]:
    """Return the bound providers whose ``verified`` date is missing or too old.

    A provider is bound when some harness names it as ``default_provider``.
    It is stale when ``providers.<name>.verified`` is absent, unreadable, or
    older than ``review_after_days`` (default 5) before ``today``.
    """
    harnesses = bindings.data.get("harnesses")
    if not isinstance(harnesses, dict):
        return []
    bound = {
        entry.get("default_provider")
        for entry in harnesses.values()
        if isinstance(entry, dict) and isinstance(entry.get("default_provider"), str)
    }

    review_after = bindings.data.get("review_after_days", DEFAULT_REVIEW_AFTER_DAYS)
    if not isinstance(review_after, int) or isinstance(review_after, bool) or review_after < 0:
        review_after = DEFAULT_REVIEW_AFTER_DAYS
    oldest_fresh = today - timedelta(days=review_after)

    providers = bindings.data.get("providers")
    providers = providers if isinstance(providers, dict) else {}
    stale = []
    for name in sorted(bound):
        meta = providers.get(name)
        verified = _as_date(meta.get("verified")) if isinstance(meta, dict) else None
        if verified is None or verified < oldest_fresh:
            stale.append(name)
    return stale
