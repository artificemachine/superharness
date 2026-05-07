"""MCP skills tool — Iteration 8."""
from __future__ import annotations

import os
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


def get_skills(
    manifests_dir: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """Return agent skill manifests, optionally filtered by tag.

    *manifests_dir* defaults to the package's adapter_manifests directory.
    """
    if manifests_dir is None:
        try:
            import importlib.resources as _res
            manifests_dir = str(_res.files("superharness").joinpath("adapter_manifests"))
        except Exception:
            return []

    if not os.path.isdir(manifests_dir):
        return []

    results = []
    for fname in sorted(os.listdir(manifests_dir)):
        if not (fname.endswith(".yaml") or fname.endswith(".yml")):
            continue
        path = os.path.join(manifests_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                if yaml:
                    data = yaml.safe_load(f) or {}
                else:
                    data = {}
        except Exception:
            continue

        if tag:
            manifest_tags = data.get("tags", [])
            if isinstance(manifest_tags, str):
                manifest_tags = [t.strip() for t in manifest_tags.split(",")]
            if tag not in manifest_tags:
                continue

        results.append(data)

    return results
