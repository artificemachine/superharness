"""One-way import of task fields from a GitHub/GitLab issue.

Snapshot only: fetches an issue via `gh`/`glab` at task-create time and
maps it to task fields. Never writes back to the issue and never re-syncs
after import (see docs/PLAN-issue-link.md).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from urllib.parse import urlparse

_CHECKLIST_RE = re.compile(r"^\s*-\s*\[[ xX]\]\s+(.*)$", re.MULTILINE)


def _detect_platform(url: str) -> str:
    """Return 'github' for github.com, 'gitlab' for anything else
    (gitlab.com, self-hosted GitLab CE such as gitlab.gs)."""
    host = urlparse(url).netloc.lower()
    return "github" if host == "github.com" else "gitlab"


def _parse_checklist(body: str) -> list[str]:
    return [m.strip() for m in _CHECKLIST_RE.findall(body or "")]


def _fetch_issue(url: str) -> dict:
    """Shell to gh/glab to fetch title/body/labels for an issue URL.
    Raises RuntimeError with a one-line, actionable message on any failure."""
    platform = _detect_platform(url)
    binary = "gh" if platform == "github" else "glab"

    if shutil.which(binary) is None:
        raise RuntimeError(
            f"'{binary}' CLI not found on PATH; install it to use --from-issue"
        )

    if platform == "github":
        argv = [binary, "issue", "view", url, "--json", "title,body,labels"]
    else:
        argv = [binary, "issue", "view", url, "-F", "json"]

    result = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(
            f"{binary} issue view failed: {result.stderr.strip()[:300]}"
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{binary} returned non-JSON output for issue view: {e}") from e


def _issue_to_task_fields(issue: dict, issue_url: str) -> dict:
    body = issue.get("body") or ""
    return {
        "title": issue.get("title") or "",
        "context": body,
        "acceptance_criteria": _parse_checklist(body),
        "issue_url": issue_url,
    }
