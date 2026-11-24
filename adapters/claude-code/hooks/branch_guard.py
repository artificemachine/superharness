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

Destructive operations (reset --hard, clean -f, checkout -- ., rm -rf on a root, a
home or a top-level folder) are judged on parsed commands too, never on quoted text,
and are refused with their reason instead of asked: an agent session has nobody at
the terminal, so a confirmation prompt only stalls it. SUPERHARNESS_CONFIRM_MODE=ask
restores the old prompts for an interactive human session.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

PROTECTED = {"main", "master"}

# Tokens that end one command and start another, as shlex reports them with punctuation_chars.
SEPARATORS = {"&&", "||", ";", "|", "&", ";;", "|&", "\n"}

# rm -rf on any of these is refused: the filesystem root, a home, the parent folder, or everything in one of them.
DANGEROUS_RM_TARGETS = {"/", "/*", "~", "~/", "~/*", "$HOME", "$HOME/", "$HOME/*", "${HOME}", "..", "../", "*", "."}

# A destructive operation named somewhere in a command that does not parse.
DESTRUCTIVE_TEXT = re.compile(r"git\s+(reset\s+--hard|clean\s+-\w*f|checkout\s+--\s+\./?(?:\s|$))|rm\s+-\w*[rR]")

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


def refuse_or_ask(reason: str) -> None:
    """Refuse with the reason (default), or ask when the session is an interactive human one."""
    if os.environ.get("SUPERHARNESS_CONFIRM_MODE", "deny") == "ask":
        emit("ask", reason)
    emit("deny", reason + " Do it another way (a narrower command, a new branch, a backup first), "
                          "or ask the owner in the conversation; this hook never prompts.")


def commands(command: str) -> list[list[str]] | None:
    """The simple commands of a shell line as token lists, quotes removed; None when it does not parse."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    result, current = [], []
    for token in tokens:
        if token in SEPARATORS or set(token) <= set(";&|()"):
            if current:
                result.append(current)
            current = []
        else:
            current.append(token)
    if current:
        result.append(current)
    return result


def destructive(tokens: list[str]) -> str | None:
    """The destructive operation this simple command performs, or None."""
    words = list(tokens)
    # Leading VAR=value assignments and wrappers do not change what runs.
    while words and (words[0] in ("sudo", "command", "exec", "nohup", "env", "time") or
                     ("=" in words[0] and not words[0].startswith("-"))):
        words = words[1:]
    if not words:
        return None
    if words[0] == "git":
        rest = [w for w in words[1:] if not w.startswith("-C")]
        sub = next((w for w in rest if not w.startswith("-")), None)
        args = rest[rest.index(sub) + 1:] if sub else []
        if sub == "reset" and "--hard" in args:
            return "git reset --hard"
        if sub == "clean" and any(a == "--force" or (a.startswith("-") and not a.startswith("--") and "f" in a)
                                  for a in args):
            return "git clean -f"
        if sub == "checkout" and "--" in args and any(a in (".", "./") for a in args[args.index("--") + 1:]):
            return "git checkout -- ."
        return None
    if words[0] == "rm":
        flags = "".join(w[1:] for w in words[1:] if w.startswith("-") and not w.startswith("--"))
        long_flags = {w for w in words[1:] if w.startswith("--")}
        recursive = "r" in flags or "R" in flags or "--recursive" in long_flags
        if not recursive:
            return None
        for target in (w for w in words[1:] if not w.startswith("-")):
            path = target.rstrip("/") or "/"
            top_level = path.startswith("/") and path.count("/") == 1
            if target in DANGEROUS_RM_TARGETS or path in DANGEROUS_RM_TARGETS or top_level:
                return "rm -r " + target
    return None


def current_branch() -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
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
    for tok in tokens[idx + 1 :]:
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
            dst = dst[len("refs/heads/") :]
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
            refuse_or_ask("superharness: branch-guard could not parse the tool input.")
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
        if len(tokens) > tokens.index("push") + 1 and tokens[
            tokens.index("push") + 1
        ].startswith("gitlab"):
            continue

        if "--force" in tokens and "--force-with-lease" not in tokens:
            emit(
                "deny",
                "superharness: BLOCKED — bare --force push is destructive. "
                "Use --force-with-lease instead.",
            )

        targets = push_targets(tokens)
        if targets is None:
            refuse_or_ask(
                "superharness: branch-guard could not determine the push target of this command; "
                "push with an explicit remote and branch name."
            )
        hits = [t for t in targets if t in PROTECTED]
        if hits:
            emit(
                "deny",
                f"superharness: BLOCKED — this would push to "
                f"{', '.join(sorted(set(hits)))}. Never push directly to a "
                f"protected branch. Use a feature branch and PR.",
            )

    parsed = commands(command)
    if parsed is None:
        if DESTRUCTIVE_TEXT.search(command):
            refuse_or_ask("superharness: BLOCKED — a destructive operation in a command that does not parse.")
        emit("allow")
    for tokens in parsed:
        operation = destructive(tokens)
        if operation:
            refuse_or_ask(f"superharness: BLOCKED — destructive operation `{operation}`.")

    emit("allow")


if __name__ == "__main__":
    main()
