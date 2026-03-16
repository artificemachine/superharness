#!/bin/bash
# PreToolUse hook: Branch Guard
# Fires before every Bash command. Blocks git push to main/master.
# Also warns on destructive git operations.
#
# Input: JSON on stdin with tool_input.command
# Output: JSON with decision (allow/warn/block) and optional message

INPUT=$(cat)
COMMAND=$(printf '%s' "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

# Fail-closed: if JSON parsing failed, warn rather than silently allowing
if [ -z "$COMMAND" ] && [ -n "$INPUT" ]; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": "superharness: branch-guard could not parse tool input. Proceeding with caution."}}'
  exit 0
fi

# Block push to main/master
if echo "$COMMAND" | grep -qE 'git\s+push.*\b(main|master)\b'; then
  cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "superharness: BLOCKED — never push directly to main/master. Use a feature branch and PR."
  }
}
EOF
  exit 0
fi

# Block force push
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*--force'; then
  cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "superharness: BLOCKED — force push is destructive. Review and use a safer approach."
  }
}
EOF
  exit 0
fi

# Warn on destructive git operations
if echo "$COMMAND" | grep -qE 'git\s+(reset\s+--hard|clean\s+-f|checkout\s+--\s+\.)'; then
  cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask",
    "permissionDecisionReason": "superharness: WARNING — destructive git operation detected. Make sure this is intentional."
  }
}
EOF
  exit 0
fi

# Warn on rm -rf
if echo "$COMMAND" | grep -qE 'rm\s+-rf\s+/'; then
  cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask",
    "permissionDecisionReason": "superharness: WARNING — recursive delete on root path. Double-check the target."
  }
}
EOF
  exit 0
fi

# Allow everything else
echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
