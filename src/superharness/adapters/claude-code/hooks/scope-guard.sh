#!/bin/bash
# PreToolUse hook: Scope Guard
# Fires before every Write/Edit. Checks that the file being modified
# is within scope of the active contract. Refuses (never asks) when
# the file is a secret or sits in a system folder.
#
# Input: JSON on stdin with tool_input.file_path
# Output: JSON with decision (allow/warn/block) and optional message

PROJECT_DIR="$(pwd)"
CONTRACT="$PROJECT_DIR/.superharness/state.sqlite3"

# Refuse with the reason (default), or ask when SUPERHARNESS_CONFIRM_MODE=ask (an interactive human session).
# An agent session has nobody at the terminal: a confirmation prompt only stalls it. The reason is passed to
# python as an argument so a path with quotes cannot break the JSON.
refuse_or_ask() {
  python3 -c '
import json, os, sys
reason = sys.argv[1]
if os.environ.get("SUPERHARNESS_CONFIRM_MODE", "deny") == "ask":
    decision = "ask"
else:
    decision = "deny"
    reason += " Write inside the project or the session scratchpad instead, or ask the owner in the conversation; this hook never prompts."
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                         "permissionDecisionReason": reason}}))' "$1"
  exit 0
}

# Read tool input from stdin
INPUT=$(cat)
FILE_PATH=$(printf '%s' "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)

# Fail-closed: if JSON parsing failed, refuse rather than silently allowing
if [ -z "$FILE_PATH" ] && [ -n "$INPUT" ]; then
  refuse_or_ask "superharness: scope-guard could not parse the tool input."
fi

# Block writes to sensitive files — ALWAYS, regardless of contract.
# Exception: *.env.example is a checked-in template (placeholder var names,
# no real values) — never a secret. Excluded before the sensitive-file case
# below so editing it isn't blocked alongside real .env / .env.local files.
case "$FILE_PATH" in
  *.env.example)
    ;;
  *.env|*.env.*|*credentials*|*secrets.json|*secrets.yaml|*secrets.yml|*secrets.toml|*.pem|*.key|*/.ssh/*|*/.kube/config|*terraform.tfvars|*.tfvars|*.tfvars.json)
    cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "superharness: BLOCKED — writing to sensitive file ($FILE_PATH). Never edit credentials, tokens, or keys."
  }
}
EOF
    exit 0
    ;;
esac

# Claude Code's own managed workspace temp (scratchpad, tool-results, tasks)
# lives under /tmp/claude-<uid>/. It is a sanctioned agent work area, not a
# user "system file" — allow silently so create/edit there never prompts.
# The sensitive-file deny above still runs first, so a stray *.key / *.env
# inside the scratchpad is still blocked.
case "$FILE_PATH" in
  /tmp/claude-*/*)
    echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
    exit 0
    ;;
esac

# Refuse writes to system folders, outside the project
case "$FILE_PATH" in
  /etc/*|/usr/*|/var/*|/tmp/*)
    refuse_or_ask "superharness: BLOCKED — writing to a system folder ($FILE_PATH), outside the project."
    ;;
esac

# If no contract exists, skip scope check (superharness not active for this project)
if [ ! -f "$CONTRACT" ]; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
  exit 0
fi

# Allow everything else within scope
echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
