"""Smart dispatch routing — choose the best agent for a task by skill match.

Loads adapter manifests from `<project>/.superharness/adapter_manifests/` (or
the bundled manifests), scores each agent against the task's required skills
(derived from its title, description, and tags), and returns the best-matching
agent name.

Usage::

    from superharness.engine.smart_dispatch import choose_agent

    agent = choose_agent(task, project_dir="/path/to/project")
    # → "claude-code" | "codex-cli" | "gemini-cli" | ...
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FALLBACK_AGENT = "claude-code"

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


def _load_manifests(manifests_dir: str) -> list[dict[str, Any]]:
    """Load all adapter manifests from a directory."""
    p = Path(manifests_dir)
    if not p.is_dir():
        return []
    manifests: list[dict[str, Any]] = []
    for yaml_file in sorted(p.glob("*.yaml")):
        try:
            with yaml_file.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) if yaml else {}
            if isinstance(data, dict) and data.get("name"):
                manifests.append(data)
        except Exception as exc:
            logger.debug("smart_dispatch: failed to load %s: %s", yaml_file, exc)
    return manifests


def _manifests_dir(project_dir: str | None) -> str:
    """Resolve the adapter manifests directory for a project or bundled fallback."""
    if project_dir:
        candidate = os.path.join(project_dir, ".superharness", "adapter_manifests")
        if os.path.isdir(candidate):
            return candidate
    # Bundled manifests inside the package
    bundled = Path(__file__).parent.parent / "adapter_manifests"
    return str(bundled)


def _task_keywords(task: dict[str, Any]) -> set[str]:
    """Extract lowercase keywords from task fields for matching."""
    tokens: set[str] = set()
    for field in ("title", "description", "tags", "category", "effort"):
        val = task.get(field)
        if isinstance(val, str):
            tokens.update(val.lower().split())
        elif isinstance(val, list):
            for item in val:
                tokens.update(str(item).lower().split())
    return tokens


def _score(manifest: dict[str, Any], keywords: set[str]) -> int:
    """Score an adapter manifest against task keywords.

    Returns the number of manifest tags/skills that appear in keywords.
    """
    score = 0
    for field in ("tags", "skills", "strengths"):
        vals = manifest.get(field) or []
        if isinstance(vals, str):
            vals = [vals]
        for tag in vals:
            if str(tag).lower() in keywords:
                score += 1
    return score


def choose_agent(
    task: dict[str, Any],
    project_dir: str | None = None,
    manifests_dir: str | None = None,
) -> str:
    """Return the best-matching agent name for a task.

    Args:
        task: Task dict with at minimum an ``owner`` field.
        project_dir: Project root (used to find adapter manifests).
        manifests_dir: Override the manifests directory directly.

    Returns:
        Agent name string (e.g. "claude-code").  Falls back to the task's
        ``owner`` field, then to "claude-code" if no match is found.
    """
    explicit_owner = task.get("owner")

    mdir = manifests_dir or _manifests_dir(project_dir)
    manifests = _load_manifests(mdir)

    if not manifests:
        logger.debug("smart_dispatch: no manifests found in %s, using owner/fallback", mdir)
        return explicit_owner or _FALLBACK_AGENT

    keywords = _task_keywords(task)
    if not keywords:
        return explicit_owner or _FALLBACK_AGENT

    best_agent: str | None = None
    best_score = -1

    for manifest in manifests:
        name = manifest.get("name", "")
        s = _score(manifest, keywords)
        if s > best_score:
            best_score = s
            best_agent = name

    if best_score <= 0 or not best_agent:
        logger.debug(
            "smart_dispatch: no skill match (best_score=%d), falling back to %s",
            best_score, explicit_owner or _FALLBACK_AGENT
        )
        return explicit_owner or _FALLBACK_AGENT

    if best_agent != explicit_owner and explicit_owner:
        logger.info(
            "smart_dispatch: routing '%s' to '%s' (score=%d, owner was '%s')",
            task.get("id", "?"), best_agent, best_score, explicit_owner
        )

    return best_agent
