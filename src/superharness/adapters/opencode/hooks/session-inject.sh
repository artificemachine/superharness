#!/bin/bash
# superharness session-inject hook for OpenCode
#
# Checks for pending discussion prompt files (.prompt.md) and surfaces them.
# Run this at session start or on-demand to pick up discussion tasks dispatched
# via the session-inject mechanism.
#
# Usage: source this file to set up a periodic check, or run directly.
#   bash session-inject.sh [project_dir]

set -euo pipefail

PROJECT_DIR="${1:-$(pwd)}"
SH_DIR="$PROJECT_DIR/.superharness"

[ -d "$SH_DIR" ] || exit 0

DISC_DIR="$SH_DIR/discussions"
[ -d "$DISC_DIR" ] || exit 0

FOUND=0

for prompt_file in "$DISC_DIR"/*/round-*-opencode.prompt.md; do
    [ -f "$prompt_file" ] || continue
    FOUND=1
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  📋 PENDING DISCUSSION TASK                                 ║"
    echo "╠══════════════════════════════════════════════════════════════╣"
    echo "║  File: $(basename "$(dirname "$prompt_file")")/$(basename "$prompt_file")"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    cat "$prompt_file"
    echo ""
    echo "---"
    echo "To respond: write your verdict to the .yaml file listed above,"
    echo "or use: shux discuss submit --project $PROJECT_DIR --id <disc_id> --round <N> --verdict <agree|disagree|partial|consensus|abstain>"
    echo ""

    # Mark as seen by touching the file (mtime update signals consumption)
    touch "$prompt_file"
done

if [ $FOUND -eq 0 ]; then
    exit 0
fi

echo "📋 $FOUND pending discussion task(s) surfaced above."
