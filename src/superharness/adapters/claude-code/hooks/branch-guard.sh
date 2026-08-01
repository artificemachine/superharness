#!/bin/bash
# PreToolUse hook: Branch Guard
# Fires before every Bash command. Blocks pushes to protected branches and bare
# --force pushes; warns on destructive git operations.
#
# Input: JSON on stdin with tool_input.command
# Output: JSON with permissionDecision (allow/ask/deny)
#
# The logic lives in branch_guard.py — telling a feature-branch push apart from a
# push to main needs real tokenization, and regexes over the whole command string
# got that wrong in both directions. See that file's docstring.

exec python3 "$(dirname "${BASH_SOURCE[0]}")/branch_guard.py"
