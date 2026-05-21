"""Capture and replay environment variables for background watcher dispatch.

Background daemons (launchd, systemd) run in a sterile environment without
API keys or user PATH. This module snapshots essential env vars at install
time and replays them at dispatch time.
"""
from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import yaml

import logging
logger = logging.getLogger(__name__)

ENV_FILENAME = "watcher-env.yaml"

# Keys to always capture if present.
_ESSENTIAL_KEYS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "CLAUDE_API_KEY",
    "CLAUDE_CODE_USE_BEDROCK",
    "AWS_PROFILE",
    "AWS_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "GOOGLE_API_KEY",
    "PATH",
    "HOME",
    "USER",
    "SHELL",
    "LANG",
    "TERM",
    "SUPERHARNESS_FORCE_NO_SDK",
]


def snapshot(project_dir: Path) -> Path:
    """Capture essential env vars to .superharness/watcher-env.yaml (chmod 600).

    Returns the path to the written file.
    """
    harness = project_dir / ".superharness"
    if not harness.is_dir():
        raise FileNotFoundError(f"Missing .superharness in {project_dir}")

    captured: dict[str, str] = {}
    for key in _ESSENTIAL_KEYS:
        val = os.environ.get(key)
        if val is not None:
            captured[key] = val

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {
        "captured_at": now,
        "env": captured,
    }

    env_file = harness / ENV_FILENAME
    env_file.write_text(yaml.dump(doc, default_flow_style=False), encoding="utf-8")
    env_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600

    # Ensure watcher-env.yaml is in .gitignore
    _ensure_gitignored(project_dir)

    return env_file


def load(project_dir: Path) -> dict[str, str]:
    """Load captured env vars from .superharness/watcher-env.yaml.

    Returns a dict of env vars to merge into subprocess environment.
    Returns empty dict if file missing or unreadable.
    """
    env_file = project_dir / ".superharness" / ENV_FILENAME
    if not env_file.exists():
        return {}
    try:
        doc = yaml.safe_load(env_file.read_text(encoding="utf-8")) or {}
        return doc.get("env", {})
    except Exception as e:
        logger.warning("env_snapshot.py unexpected error: %s", e, exc_info=True)
        return {}


def merge_env(project_dir: Path) -> dict[str, str]:
    """Return a copy of os.environ merged with captured watcher env.

    Captured values fill in missing keys but do NOT override existing env vars.
    This means a foreground watcher with real env vars works unchanged,
    while a daemon gets the captured values.
    """
    captured = load(project_dir)
    merged = os.environ.copy()
    for key, val in captured.items():
        if key not in merged or not merged[key]:
            merged[key] = val
    return merged


def check(project_dir: Path) -> tuple[str, list[str]]:
    """Doctor check: verify watcher-env.yaml exists and is healthy.

    Returns (status, messages) where status is 'PASS', 'WARN', or 'FAIL'.
    """
    env_file = project_dir / ".superharness" / ENV_FILENAME
    messages: list[str] = []

    if not env_file.exists():
        return "WARN", [
            f"watcher-env.yaml not found — watcher may fail to launch agents",
            f"Run: shux watcher-worker --project {project_dir} to create it",
        ]

    # Check permissions (should be 0600)
    try:
        mode = env_file.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            messages.append("watcher-env.yaml is readable by group/others — should be chmod 600")
            messages.append(f"Run: chmod 600 {env_file}")
    except OSError:
        pass

    # Check content
    try:
        doc = yaml.safe_load(env_file.read_text(encoding="utf-8")) or {}
        env_vars = doc.get("env", {})
        has_anthropic = bool(env_vars.get("ANTHROPIC_API_KEY"))
        has_openai = bool(env_vars.get("OPENAI_API_KEY"))
        has_path = bool(env_vars.get("PATH"))

        if not has_anthropic and not has_openai:
            messages.append("watcher-env.yaml has no API keys — agents will fail to authenticate")
            messages.append("Re-run: shux watcher-worker --project . (with API keys in your shell)")
            return "WARN", messages

        if not has_path:
            messages.append("watcher-env.yaml missing PATH — agent CLIs may not be found")

        captured_at = doc.get("captured_at", "unknown")
        keys = [k for k in env_vars if k != "PATH"]
        status = "PASS"
        if messages:
            status = "WARN"
        messages.insert(0, f"watcher-env.yaml ok (captured {captured_at}, {len(keys)} keys)")
        return status, messages

    except Exception as e:
        return "FAIL", [f"watcher-env.yaml unreadable: {e}"]


def _ensure_gitignored(project_dir: Path) -> None:
    """Add watcher-env.yaml to .gitignore if not already present."""
    gitignore = project_dir / ".gitignore"
    marker = ".superharness/watcher-env.yaml"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if marker in content:
            return
        if not content.endswith("\n"):
            content += "\n"
        content += f"# Watcher env snapshot (contains API keys)\n{marker}\n"
        gitignore.write_text(content, encoding="utf-8")
    else:
        gitignore.write_text(f"# Watcher env snapshot (contains API keys)\n{marker}\n", encoding="utf-8")
