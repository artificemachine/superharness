"""Obsidian Semantic MCP integration bridge.

All vault interaction lives here. Three public functions:
  - vault_search       — query the osm dashboard API
  - vault_write_note   — write task completion note to vault
  - vault_append_changelog — append timestamped entry to changelog.md

All functions are fail-safe: any error is logged, never raised.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

_DEFAULT_DASH_URL = "http://localhost:8484"


def vault_search(
    query: str,
    limit: int = 3,
    dashboard_url: str | None = None,
) -> list[dict]:
    """Query the osm dashboard API.

    Returns list of {path, similarity, preview}. Returns [] on any failure.
    """
    base_url = (
        dashboard_url
        or os.environ.get("OBSIDIAN_DASH_URL", _DEFAULT_DASH_URL)
    ).rstrip("/")
    params = urllib.parse.urlencode({"q": query, "limit": limit})
    url = f"{base_url}/api/search?{params}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        results = data.get("results") if isinstance(data, dict) else data
        return results if isinstance(results, list) else []
    except Exception as e:
        log.debug("vault_search failed: %s", e)
        return []


def vault_write_note(
    vault_path: str,
    project_name: str,
    task_id: str,
    content: str,
) -> None:
    """Write task completion note to $OBSIDIAN_VAULT/superharness/<project>/<task-id>.md."""
    try:
        note_dir = os.path.join(vault_path, "superharness", project_name)
        os.makedirs(note_dir, exist_ok=True)
        note_path = os.path.join(note_dir, f"{task_id}.md")
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(content)
        log.debug("vault note written: %s", note_path)
    except Exception as e:
        log.warning("vault_write_note failed: %s", e)


def vault_append_changelog(vault_path: str, entry: str) -> None:
    """Append a timestamped entry to $OBSIDIAN_VAULT/changelog.md."""
    try:
        changelog_path = os.path.join(vault_path, "changelog.md")
        with open(changelog_path, "a", encoding="utf-8") as f:
            f.write(entry)
            if not entry.endswith("\n"):
                f.write("\n")
        log.debug("vault changelog updated: %s", changelog_path)
    except Exception as e:
        log.warning("vault_append_changelog failed: %s", e)
