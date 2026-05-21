"""Skill extraction — learn reusable patterns from completed tasks.

When a task is marked done, analyze the task metadata and git diff to
extract a compact skill entry and append it to .superharness/skills.yaml.

Skills are surfaced during delegate context-hint building so future agents
can reuse proven approaches without rediscovering them.
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import logging
logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


# ---------------------------------------------------------------------------
# Category inference
# ---------------------------------------------------------------------------

_CATEGORY_SIGNALS: list[tuple[str, list[str]]] = [
    ("security", ["security", "auth", "secret", "credential", "cve", "vulnerability"]),
    ("test", ["pytest", "unittest", "fixture", "mock", "coverage", "assertion"]),
    ("bug-fix", ["fix", "bug", "crash", "broken", "regression", "hotfix", "patch"]),
    ("refactor", ["refactor", "cleanup", "simplify", "extract", "rename", "reorganize", "restructure"]),
    ("docs", ["readme", "changelog", "docstring", "spec"]),
    ("perf", ["perf", "performance", "speed", "cache", "optimiz", "benchmark", "latency"]),
    ("config", ["config.yaml", "settings", "toml", "dockerfile"]),
    ("feature", ["feat", "feature", "implement", "support", "introduce"]),
]


def _infer_category(text: str) -> str:
    lowered = text.lower()
    best = "feature"
    for category, signals in _CATEGORY_SIGNALS:
        if any(s in lowered for s in signals):
            return category
    return best


# ---------------------------------------------------------------------------
# Technique extraction
# ---------------------------------------------------------------------------

_TECHNIQUE_KEYWORDS = [
    # Python patterns
    "dataclass", "decorator", "context manager", "generator", "async", "threading",
    "subprocess", "pathlib", "argparse", "unittest.mock", "pytest.fixture",
    # Git patterns
    "worktree", "rebase", "cherry-pick", "stash",
    # Architecture patterns
    "fanout", "swarm", "dispatch", "registry", "factory", "singleton", "plugin",
    "middleware", "hook", "event", "callback", "observer",
    # Data patterns
    "yaml", "json", "csv", "sqlite", "cache", "index",
    # Ops patterns
    "launchd", "systemd", "cron", "daemon", "signal", "lock", "mutex",
    # Test patterns
    "parametrize", "fixture", "mock", "patch", "monkeypatch", "tmp_path",
]


def _extract_techniques(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for kw in _TECHNIQUE_KEYWORDS:
        if kw in lowered and kw not in found:
            found.append(kw)
    return found[:8]  # cap at 8 techniques


# ---------------------------------------------------------------------------
# Git diff analysis
# ---------------------------------------------------------------------------

def _get_diff_summary(project_dir: str, base_ref: str = "HEAD~1") -> dict[str, Any]:
    """Get a compact summary of changes since base_ref."""
    summary: dict[str, Any] = {
        "files_changed": 0,
        "insertions": 0,
        "deletions": 0,
        "file_types": [],
        "test_files_changed": False,
    }
    try:
        r = subprocess.run(
            ["git", "diff", "--shortstat", base_ref, "HEAD"],
            capture_output=True, text=True, check=False, cwd=project_dir,
        )
        if r.returncode == 0 and r.stdout.strip():
            m = re.search(r"(\d+) files? changed", r.stdout)
            if m:
                summary["files_changed"] = int(m.group(1))
            m = re.search(r"(\d+) insertions?\(\+\)", r.stdout)
            if m:
                summary["insertions"] = int(m.group(1))
            m = re.search(r"(\d+) deletions?\(-\)", r.stdout)
            if m:
                summary["deletions"] = int(m.group(1))

        # Get file list
        r2 = subprocess.run(
            ["git", "diff", "--name-only", base_ref, "HEAD"],
            capture_output=True, text=True, check=False, cwd=project_dir,
        )
        if r2.returncode == 0:
            files = [f.strip() for f in r2.stdout.splitlines() if f.strip()]
            # Extract unique extensions
            exts = list({Path(f).suffix for f in files if Path(f).suffix})[:5]
            summary["file_types"] = exts
            summary["test_files_changed"] = any(
                "test" in f.lower() or f.startswith("tests/") for f in files
            )
    except Exception as e:
        logger.warning("skill_extractor.py unexpected error: %s", e, exc_info=True)
        pass
    return summary


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

@dataclass
class ExtractedSkill:
    task_id: str
    title: str
    category: str
    summary: str
    techniques: list[str] = field(default_factory=list)
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    test_coverage: bool = False
    tdd_used: bool = False
    date: str = ""


def extract_skill_from_task(project_dir: str, task: dict) -> ExtractedSkill | None:
    """Extract a reusable skill entry from a completed task dict.

    Returns None if there is not enough info to extract a useful skill.
    """
    task_id = str(task.get("id", ""))
    title = str(task.get("title", ""))
    if not task_id or not title:
        return None

    # Build text corpus for analysis
    corpus_parts = [title]
    summary = str(task.get("summary", "") or "")
    corpus_parts.append(summary)

    tdd = task.get("tdd") or {}
    tdd_text = " ".join(str(v) for v in tdd.values())
    corpus_parts.append(tdd_text)

    ac = task.get("acceptance_criteria") or []
    corpus_parts.extend(str(c) for c in ac)

    corpus = " ".join(corpus_parts)
    category = _infer_category(corpus)
    techniques = _extract_techniques(corpus)
    tdd_used = bool(tdd.get("red") or tdd.get("green"))

    diff = _get_diff_summary(project_dir)

    # Compact skill summary: title + first sentence of summary
    short_summary = summary.split(".")[0].strip()[:200] if summary else title

    return ExtractedSkill(
        task_id=task_id,
        title=title,
        category=category,
        summary=short_summary,
        techniques=techniques,
        files_changed=diff["files_changed"],
        insertions=diff["insertions"],
        deletions=diff["deletions"],
        test_coverage=diff["test_files_changed"],
        tdd_used=tdd_used,
        date=time.strftime("%Y-%m-%d", time.gmtime()),
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _load_skills(skills_file: str) -> dict:
    if yaml is None:
        return {"skills": []}
    p = Path(skills_file)
    if not p.exists():
        return {"skills": []}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            data = {}
        if "skills" not in data or not isinstance(data["skills"], list):
            data["skills"] = []
        return data
    except Exception as e:
        logger.warning("skill_extractor.py unexpected error: %s", e, exc_info=True)
        return {"skills": []}


def _save_skills(skills_file: str, data: dict) -> None:
    if yaml is None:
        return
    Path(skills_file).write_text(
        yaml.safe_dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def record_skill(project_dir: str, task: dict) -> ExtractedSkill | None:
    """Extract and persist a skill from a just-completed task.

    Returns the extracted skill, or None if extraction produced nothing useful.
    """
    skill = extract_skill_from_task(project_dir, task)
    if skill is None:
        return None

    skills_file = str(Path(project_dir) / ".superharness" / "skills.yaml")
    data = _load_skills(skills_file)

    # Avoid duplicates for the same task_id
    existing_ids = {e.get("task_id") for e in data["skills"]}
    if skill.task_id in existing_ids:
        return skill

    entry: dict[str, Any] = {
        "task_id": skill.task_id,
        "title": skill.title,
        "category": skill.category,
        "summary": skill.summary,
        "date": skill.date,
        "techniques": skill.techniques,
        "files_changed": skill.files_changed,
        "test_coverage": skill.test_coverage,
        "tdd_used": skill.tdd_used,
    }
    data["skills"].append(entry)

    try:
        _save_skills(skills_file, data)
    except Exception as e:
        logger.warning("skill_extractor.py unexpected error: %s", e, exc_info=True)
        pass
    return skill


def search_skills(project_dir: str, query: str, top_n: int = 5) -> list[dict]:
    """Search the skills library for entries relevant to a query.

    Returns up to top_n skill entries sorted by relevance (simple keyword score).
    """
    skills_file = str(Path(project_dir) / ".superharness" / "skills.yaml")
    data = _load_skills(skills_file)
    if not data["skills"]:
        return []

    query_lower = query.lower()
    query_words = set(re.findall(r'[a-z]{3,}', query_lower))

    scored: list[tuple[int, dict]] = []
    for entry in data["skills"]:
        text = " ".join([
            entry.get("title", ""),
            entry.get("summary", ""),
            entry.get("category", ""),
            " ".join(entry.get("techniques", [])),
        ]).lower()
        score = sum(1 for w in query_words if w in text)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:top_n]]


def get_skill_hints(project_dir: str, task: dict) -> list[str]:
    """Return relevant skill hints for a task, for injection into dispatch context.

    Called by _build_context_hint in delegate.py.
    """
    title = str(task.get("title", ""))
    corpus = title
    for ac in (task.get("acceptance_criteria") or []):
        corpus += " " + str(ac)

    matches = search_skills(project_dir, corpus, top_n=3)
    if not matches:
        return []

    hints = []
    for m in matches:
        tdd_flag = " [TDD]" if m.get("tdd_used") else ""
        test_flag = " [tests]" if m.get("test_coverage") else ""
        hint = (
            f"Prior skill [{m.get('category', '?')}]{tdd_flag}{test_flag}: "
            f"{m.get('title', '')} — {m.get('summary', '')}"
        )
        if m.get("techniques"):
            hint += f" (techniques: {', '.join(m['techniques'][:4])})"
        hints.append(hint)

    return hints
