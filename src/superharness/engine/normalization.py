"""Shared normalization helpers for contract fields.

PyYAML loads YAML `none` as the string "none" (not Python None), so every
consumer of contract.yaml has to filter the same set of null-equivalent
sentinels. Centralizing that logic here keeps adapter-payload output and
dashboard rendering in lockstep.
"""
from __future__ import annotations

from typing import Any

_NULL_SENTINELS = frozenset({"", "none", "null", "~"})


def normalize_blocked_by(value: Any) -> list[str]:
    """Normalize a contract `blocked_by` / `dependency` field to list[str].

    Accepts None, scalar (str / int / YAML null), or list. Collapses all
    null-equivalent forms (`None`, `""`, `"none"`, `"null"`, `"~"`) to an
    empty list. Always returns a fresh list.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if item is not None and str(item).strip().lower() not in _NULL_SENTINELS
        ]
    text = str(value).strip()
    if text.lower() in _NULL_SENTINELS:
        return []
    return [text]
