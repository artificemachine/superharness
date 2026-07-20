"""Iteration 8 — the README must show the tool concretely above the fold.

Open since the 2026-07-19 job-ready audit: a reader skimming the top of
README.md could not tell what running superharness actually looks like.

The original plan specified a screenshot or GIF. That was reconsidered: the
requirement is "demonstrate the tool concretely near the top", and an image
is only one way to satisfy it. A pasted `shux status` block does it with no
binary commit (the repo's pre-commit hook blocks media by default), renders
everywhere including plain-text mirrors, and shows real CLI output rather
than a screenshot that goes stale on the next UI change. So this test accepts
either: a real (non-badge) image/animation, or a fenced console block showing
command output.

What it will not accept is the status quo that failed the audit — a header of
CI/PyPI/license badges and prose, with nothing showing the tool in use.
"""
from __future__ import annotations

import re
from pathlib import Path

_README = Path(__file__).resolve().parents[2] / "README.md"

_HEAD_LINES = 40

# Markdown image syntax `![alt](path)` and raw <img>/<video> tags.
_IMAGE_REF_RE = re.compile(
    r'!\[[^\]]*\]\(([^)]+)\)|<img\s[^>]*src=["\']([^"\']+)|<video\s',
    re.IGNORECASE,
)

# Status badges are not a demo — this README's header carries several, and
# they would otherwise satisfy the check without anything being demonstrated.
_BADGE_HOST_RE = re.compile(
    r'shields\.io|badge\.fury\.io|/actions/workflows/.*badge\.svg|/workflows/.*/badge\.svg',
    re.IGNORECASE,
)

# Animations are never badges, so the extension alone is sufficient signal.
_ANIMATION_EXT_RE = re.compile(r'\.(?:gif|mp4|webm)\b', re.IGNORECASE)

# A fenced block tagged as terminal output, containing a shux invocation.
_CONSOLE_FENCE_RE = re.compile(
    r'```(?:console|shell|shell-session|text)\b(.*?)```',
    re.IGNORECASE | re.DOTALL,
)


def _has_demo_image(head: str) -> bool:
    if _ANIMATION_EXT_RE.search(head):
        return True
    for m in _IMAGE_REF_RE.finditer(head):
        target = m.group(1) or m.group(2) or ""
        if target and not _BADGE_HOST_RE.search(target):
            return True
    return False


def _has_console_demo(head: str) -> bool:
    """A fenced console block that actually shows the tool running.

    Requires a `shux`/`superharness` invocation *and* more than a couple of
    output lines, so a bare install snippet cannot pass for a demonstration.
    """
    for m in _CONSOLE_FENCE_RE.finditer(head):
        body = m.group(1)
        if not re.search(r'\b(?:shux|superharness)\b', body):
            continue
        if len([ln for ln in body.splitlines() if ln.strip()]) >= 4:
            return True
    return False


def test_readme_demonstrates_the_tool_above_the_fold():
    head = "\n".join(_README.read_text(encoding="utf-8").splitlines()[:_HEAD_LINES])

    assert _has_demo_image(head) or _has_console_demo(head), (
        f"README.md must demonstrate the tool within its first {_HEAD_LINES} "
        "lines — either a non-badge image/animation, or a fenced console block "
        "showing real `shux` output with at least 4 lines. Status badges and "
        "prose alone do not satisfy this. See "
        "docs/audits/2026-07-20-job-ready-v2.md for the original finding."
    )


def test_status_badges_alone_do_not_satisfy_the_demo_requirement():
    """Guard the guard: the badge-only header that failed the audit must not
    pass, otherwise this test would silently stop protecting anything."""
    badges_only = (
        "# superharness\n"
        "[![CI](https://github.com/o/r/actions/workflows/tests.yml/badge.svg)](x)\n"
        "[![PyPI version](https://badge.fury.io/py/superharness.svg)](x)\n"
        "\n**Multi-agent task coordination**\n\nSome prose about the project.\n"
        "```bash\npipx install superharness\n```\n"
    )
    assert not _has_demo_image(badges_only)
    assert not _has_console_demo(badges_only)
