"""Privacy tag stripping for agent-authored content.

Removes <private>...</private> spans before content lands in SQLite. Applied
at every superharness write boundary (handoff, decision, failure, observation).

Pattern borrowed from thedotmack/claude-mem, but applied at the write
boundary instead of a hook layer so the strip happens once, deterministically,
and is not bypassable by skipping a hook.
"""
from __future__ import annotations

import re
from typing import Optional


PRIVATE_TAG_RE = re.compile(r"<private>.*?</private>", re.DOTALL)


def strip_private_tags(text: Optional[str]) -> str:
    """Remove every <private>...</private> span from text.

    Non-greedy matching, DOTALL so multiline spans are handled. Unmatched
    open or close tags are left intact. Empty or None input returns "".
    """
    if not text:
        return ""
    return PRIVATE_TAG_RE.sub("", text)
