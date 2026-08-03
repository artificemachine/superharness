#!/usr/bin/env python3
"""PreToolUse hook: branch guard.

Blocks pushes to a protected branch and bare --force pushes; warns on destructive
git operations.

This used to be a set of regexes run against the whole command string, which was
wrong in both directions:

  Blocked pushes that were fine, because `git\\s+push.*\\s(main|master)\\b` spans
  shell separators. A push of a feature branch was denied whenever the word "main"
  appeared later in the same tool call — in unrelated echo text, in a PR body, even
  in prose describing this bug.

  Allowed pushes that were not fine, because the pattern required whitespace before
  the branch name. `git push origin HEAD:main` has a colon, and a bare `git push`
  from a protected branch does not contain the name at all. Both sailed through.

So: split the command into segments, find the actual push invocations, and resolve
what each one would write to.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys

PROTECTED = {"main", "master"}

# Shell separators that end one command and start another. Splitting on these is
# what keeps a `git push` in one segment from being judged by text in the next.
SEGMENT_SPLIT = re.compile(r"\s*(?:&&|\|\||[;|\n])\s*")

# Flags that take a value, so the following token is not a refspec.
FLAGS_WITH_VALUE = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}


def emit(decision: str, reason: str | None = None) -> None:
    out: dict = {"hookEventName": "PreToolUse", "permissionDecision": decision}
    if reason:
        out["permissionDecisionReason"] = reason
    print(json.dumps({"hookSpecificOutput": out}))
    sys.exit(0)


def current_branch() -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    name = r.stdout.strip()
    return name if r.returncode == 0 and name and name != "HEAD" else None


def push_targets(tokens: list[str]) -> list[str] | None:
    """Branch names a `git push` would write to.

    None means "could not determine" — the caller treats that as suspicious rather
    than safe, since silently allowing an unparsed push is how the old guard let
    real violations through.
    """
    try:
        idx = tokens.index("push")
    except ValueError:
        return None

    args, skip = [], False
    for tok in tokens[idx + 1:]:
        if skip:
            skip = False
            continue
        if tok in FLAGS_WITH_VALUE:
            skip = True
            continue
        if tok.startswith("-"):
            continue
        args.append(tok)

    # First positional is the remote; the rest are refspecs.
    refspecs = args[1:] if len(args) > 1 else []

    if not refspecs:
        # Bare push (or `git push <remote>`): destination follows the current branch.
        branch = current_branch()
        return [branch] if branch else None

    targets = []
    for spec in refspecs:
        dst = spec.split(":", 1)[1] if ":" in spec else spec
        dst = dst.lstrip("+")
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        targets.append(dst)
    return targets


def main() -> None:
    raw = sys.stdin.read()
    try:
        command = json.loads(raw).get("tool_input", {}).get("command", "")
    except (ValueError, AttributeError):
        command = ""

    if not command:
        if raw.strip():
            emit("ask", "superharness: branch-guard could not parse tool input. "
                        "Proceeding with caution.")
        emit("allow")

    for segment in SEGMENT_SPLIT.split(command):
        segment = segment.strip()
        if not segment:
            continue
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue  # unbalanced quotes — another segment may still parse
        if "git" not in tokens or "push" not in tokens:
            continue

        # LAN mirror remote (gitlab.gs — private, never internet-facing).
        if len(tokens) > tokens.index("push") + 1 and tokens[tokens.index("push") + 1].startswith("gitlab"):
            continue

        if "--force" in tokens and "--force-with-lease" not in tokens:
            emit("deny", "superharness: BLOCKED — bare --force push is destructive. "
                         "Use --force-with-lease instead.")

        targets = push_targets(tokens)
        if targets is None:
            emit("ask", "superharness: branch-guard could not determine the push "
                        "target for this command. Confirm it is not a protected branch.")
        hits = [t for t in targets if t in PROTECTED]
        if hits:
            emit("deny", f"superharness: BLOCKED — this would push to "
                         f"{', '.join(sorted(set(hits)))}. Never push directly to a "
                         f"protected branch. Use a feature branch and PR.")

    if re.search(r"git\s+(reset\s+--hard|clean\s+-f|checkout\s+--\s+\.)", command):
        emit("ask", "superharness: WARNING — destructive git operation detected. "
                    "Make sure this is intentional.")

    if re.search(r"rm\s+-rf\s+/", command):
        emit("ask", "superharness: WARNING — recursive delete on root path. "
                    "Double-check the target.")

    emit("allow")


if __name__ == "__main__":
    main()
