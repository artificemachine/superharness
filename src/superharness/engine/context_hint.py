"""Context hint builder — generates agent cold-start context from task metadata.

Extracted from commands/delegate.py (C5 decomposition).
Scans acceptance criteria, TDD blocks, git history, skill hints, and failure
patterns to produce a compact context string for dispatched agents.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# Stopwords filtered from keyword extraction
_KEYWORD_STOPWORDS = frozenset({
    "that", "this", "with", "from", "have", "been", "should", "must",
    "when", "each", "into",
})
_TDD_STOPWORDS = _KEYWORD_STOPWORDS | {"test", "tests", "code", "make", "pass"}


def _extract_keywords(task: dict) -> list[str]:
    """Extract relevant keywords from acceptance criteria and TDD block."""
    keywords: list[str] = []

    for ac in task.get("acceptance_criteria") or []:
        for word in re.findall(r'[a-z_]{4,}', str(ac).lower()):
            if word not in _KEYWORD_STOPWORDS:
                keywords.append(word)

    tdd = task.get("tdd") or {}
    for phase in ("red", "green", "refactor"):
        for word in re.findall(r'[a-z_]{4,}', str(tdd.get(phase, "")).lower()):
            if word not in _TDD_STOPWORDS:
                keywords.append(word)

    # Deduplicate, top 10
    seen: set[str] = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique[:10]


def _find_relevant_files(project_dir: str, keywords: list[str]) -> list[str]:
    """Find Python source files matching the given keywords via grep."""
    src_dir = os.path.join(project_dir, "src")
    if not os.path.isdir(src_dir):
        src_dir = project_dir

    relevant: set[str] = set()
    for kw in keywords[:5]:
        try:
            r = subprocess.run(
                ["grep", "-rl", "--include=*.py", "-m", "3", kw, src_dir],
                capture_output=True, text=True, check=False, timeout=5,
            )
            for f in r.stdout.strip().splitlines()[:3]:
                if f:
                    relevant.add(os.path.relpath(f, project_dir))
        except Exception as e:
            logger.warning("Source scan failed for keyword '%s': %s", kw, e)

    return sorted(relevant)[:10]


def _get_recent_git_changes(project_dir: str) -> list[str]:
    """Return recently changed Python files from git."""
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~3"],
            capture_output=True, text=True, check=False, timeout=5,
            cwd=project_dir,
        )
        return [f for f in r.stdout.strip().splitlines() if f.endswith(".py")][:5]
    except Exception as e:
        logger.warning("Git diff failed: %s", e)
        return []


def build_context_hint(project_dir: str, task: dict) -> str:
    """Build a compact context block from task metadata to reduce agent cold-start.

    Scans acceptance criteria and TDD block for keywords, finds matching source
    files, and returns a pre-built context string the agent can use immediately.
    """
    lines: list[str] = []

    # 0. Agent memory (global + project — Hermes adaptation)
    try:
        from superharness.engine.agent_memory import get_dispatch_memory_context
        memory_context = get_dispatch_memory_context(project_dir)
        if memory_context:
            lines.append(memory_context)
    except Exception as e:
        logger.warning("Memory context injection failed: %s", e)

    # 0.5 Behavioral profile (user adaptation — Iteration 4)
    try:
        from superharness.engine.behavioral import load_profile, user_profile_path, format_profile_for_context
        profile = load_profile(os.path.join(user_profile_path(), "task_style.json"))
        # Merge all profile files
        for fname in ["task_style.json", "review_style.json", "model_prefs.json", "autonomy_profile.json"]:
            p = load_profile(os.path.join(user_profile_path(), fname))
            if p:
                profile.update({fname.replace(".json", ""): p})
        if profile:
            context = format_profile_for_context(profile, tier="standard")
            if context:
                lines.append(context)
    except Exception as e:
        logger.warning("Behavioral profile injection failed: %s", e)

    keywords = _extract_keywords(task)

    # 1. Keywords & source files
    if keywords:
        relevant_files = _find_relevant_files(project_dir, keywords)
        if relevant_files:
            lines.append("\nRelevant source files (start here, don't explore from scratch):")
            for f in relevant_files:
                lines.append(f"  - {f}")

    # 2. Recent git changes
    recent = _get_recent_git_changes(project_dir)
    if recent:
        lines.append("\nRecently changed files:")
        for f in recent:
            lines.append(f"  - {f}")

    # 3. Past skill hints
    try:
        from superharness.engine.skill_extractor import get_skill_hints
        skill_hints = get_skill_hints(project_dir, task)
        if skill_hints:
            lines.append("\nRelated past skills (reuse proven approaches):")
            for h in skill_hints:
                lines.append(f"  - {h}")
    except Exception as e:
        logger.warning("Skill hints failed: %s", e)

    # 4. Failure pattern hints + system health
    task_id = str(task.get("id", ""))
    if task_id:
        try:
            from superharness.engine.failure_patterns import get_failure_hints
            hints = get_failure_hints(project_dir, task_id)
            if hints:
                lines.append("\nPrior failure hints (avoid repeating these mistakes):")
                for h in hints:
                    lines.append(f"  - {h}")

                try:
                    from superharness.commands.doctor import get_doctor_summary
                    health = get_doctor_summary(project_dir)
                    if health:
                        lines.append("\nCurrent system health (check for environmental blockers):")
                        lines.append(health)
                except Exception as e:
                    logger.warning("Doctor summary failed: %s", e)
        except Exception as e:
            logger.warning("Failure hints failed: %s", e)

    return "\n".join(lines) if lines else ""
