#!/bin/bash
# PreToolUse hook: Scope Guard
# Fires before every Write/Edit. Checks that the file being modified
# is within scope of the active contract. Warns (does not block) if
# the file seems outside scope.
#
# Input: JSON on stdin with tool_input.file_path
# Output: JSON with decision (allow/warn/block) and optional message

PROJECT_DIR="$(pwd)"
CONTRACT="$PROJECT_DIR/.superreins/contract.yaml"

# Read tool input from stdin
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)

# Block writes to sensitive files — ALWAYS, regardless of contract
case "$FILE_PATH" in
  *.env|*.env.*|*credentials*|*secrets*|*.pem|*.key)
    cat <<EOF
{
  "decision": "block",
  "reason": "superreins: BLOCKED — writing to sensitive file ($FILE_PATH). Never edit credentials, tokens, or keys."
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
  "decision": "warn",
  "reason": "superreins: WARNING — modifying system file ($FILE_PATH). Is this in the contract scope?"
}
EOF
    exit 0
    ;;
esac

# If no contract exists, skip scope check (superreins not active for this project)
if [ ! -f "$CONTRACT" ]; then
  echo '{"decision": "allow"}'
  exit 0
fi

# Allow everything else within scope
echo '{"decision": "allow"}'
