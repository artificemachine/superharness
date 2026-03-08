#!/bin/bash
# PostToolUse hook: Auto-append to ledger
# Fires after every Write/Edit. If a .superreins/ledger.md exists,
# appends a one-line entry tracking the file change.
#
# Input: JSON on stdin with tool_input.file_path and tool_result
# Output: empty (PostToolUse hooks don't affect the tool result)

PROJECT_DIR="$(pwd)"
LEDGER="$PROJECT_DIR/.superreins/ledger.md"

# Only run if superreins is active for this project
if [ ! -f "$LEDGER" ]; then
  exit 0
fi

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)

# Skip if we can't determine the file
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Skip ledger writing to itself (prevent infinite loop)
if [[ "$FILE_PATH" == *"ledger.md"* ]]; then
  exit 0
fi

# Skip superreins protocol files (contract, handoffs)
if [[ "$FILE_PATH" == *".superreins/"* ]]; then
  exit 0
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
BASENAME=$(basename "$FILE_PATH")

echo "- $TIMESTAMP — claude-code — modified: $BASENAME" >> "$LEDGER"
