#!/bin/bash
# PreToolUse hook: Branch Guard
# Fires before every Bash command. Blocks pushes to protected branches and bare
# --force pushes; refuses destructive operations with their reason (never asks,
# unless SUPERHARNESS_CONFIRM_MODE=ask for an interactive human session).
#
# Input: JSON on stdin with tool_input.command
# Output: JSON with permissionDecision (allow/deny; ask only in the legacy mode)
#
# The logic lives in branch_guard.py — telling a feature-branch push apart from a
# push to main needs real tokenization, and regexes over the whole command string
# got that wrong in both directions. See that file's docstring.

exec python3 "$(dirname "${BASH_SOURCE[0]}")/branch_guard.py"
