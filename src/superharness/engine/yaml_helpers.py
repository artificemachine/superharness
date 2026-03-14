"""Mirrors YamlHelpers Ruby module.

Shared YAML loading helpers for all engine scripts.
Consolidates safe_load patterns from contract.py, inbox.py, and validate.py.
"""
from __future__ import annotations

import io
import os
from datetime import date, datetime
from typing import Union

import yaml  # fallback (PyYAML)

try:
    from ruamel.yaml import YAML as RuamelYAML

    _ruamel_rt = RuamelYAML()  # round-trip (default type)
    _ruamel_rt.preserve_quotes = True
except ImportError:
    _ruamel_rt = None  # type: ignore[assignment]


def safe_load(path: str, expected_class: type) -> Union[dict, list]:
    """Load a YAML file safely.

    Returns the expected type's empty value if the file is missing or contains
    nil. Raises TypeError on type mismatch.
    """
    empty: Union[dict, list] = {} if expected_class is dict else []
    if not os.path.exists(path):
        return empty
    with open(path, "r") as f:
        content = f.read()
    data = yaml.safe_load(content)
    if data is None:
        return empty
    if not isinstance(data, expected_class):
        raise TypeError(
            f"YAML document has unexpected type in {path}: "
            f"expected {expected_class.__name__}, got {type(data).__name__}"
        )
    return data


def _normalize(value: object) -> object:
    """Normalize Time/Date scalars to ISO 8601 strings, like Ruby yaml_helpers."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    return value


def safe_load_normalized(path: str, expected_class: type) -> Union[dict, list]:
    """Load and normalize Time/Date scalars to ISO 8601 strings."""
    data = safe_load(path, expected_class)
    result = _normalize(data)
    # _normalize preserves the dict/list type so cast is safe
    return result  # type: ignore[return-value]


def round_trip_load(path: str) -> object:
    """Load YAML preserving comments and formatting."""
    if _ruamel_rt is None:
        return safe_load(path, dict)
    with open(path, "r") as f:
        return _ruamel_rt.load(f)


def round_trip_dump(data: object, path: str) -> None:
    """Write YAML preserving comments and formatting."""
    if _ruamel_rt is None:
        with open(path, "w") as f:
            yaml.dump(data, f)
        return
    buf = io.StringIO()
    _ruamel_rt.dump(data, buf)
    with open(path, "w") as f:
        f.write(buf.getvalue())
