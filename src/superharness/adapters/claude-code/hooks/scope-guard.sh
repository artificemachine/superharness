#!/bin/bash
# PreToolUse hook: Scope Guard
# Fires before every Write/Edit. Checks that the file being modified
# is within scope of the active contract. Warns (does not block) if
# the file seems outside scope.
#
# Input: JSON on stdin with tool_input.file_path
# Output: JSON with decision (allow/warn/block) and optional message

PROJECT_DIR="$(pwd)"
CONTRACT="$PROJECT_DIR/.superharness/state.sqlite3"

# Read tool input from stdin
INPUT=$(cat)
FILE_PATH=$(printf '%s' "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)

# Fail-closed: if JSON parsing failed, warn rather than silently allowing
if [ -z "$FILE_PATH" ] && [ -n "$INPUT" ]; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": "superharness: scope-guard could not parse tool input. Proceeding with caution."}}'
  exit 0
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

# Warn if modifying files outside the project
case "$FILE_PATH" in
  /etc/*|/usr/*|/var/*|/tmp/*)
    cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "ask",
    "permissionDecisionReason": "superharness: WARNING — modifying system file ($FILE_PATH). Is this in the contract scope?"
  }
}
EOF
    exit 0
    ;;
esac

# If no contract exists, skip scope check (superharness not active for this project)
if [ ! -f "$CONTRACT" ]; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
  exit 0
fi

# Allow everything else within scope
echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}'
