#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHONPATH="${SRC_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# Ensure agent binaries are findable under launchd's stripped PATH.
# Inherited PATH goes first so a caller-provided override (tests, CI, custom
# installs) always wins; these are fallback dirs for when PATH is empty/minimal.
export PATH="${PATH:-}:/Applications/cmux.app/Contents/Resources/bin:${HOME}/.local/bin:${HOME}/.nvm/versions/node/v25.2.1/bin:${HOME}/.pyenv/shims:${HOME}/.pyenv/bin:/usr/local/bin:/usr/bin:/bin"

# Build Claude CLI command
CLAUDE_ARGS=()
PROMPT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      cd "$2"
      shift 2
      ;;
    --prompt)
      PROMPT="$2"
      shift 2
      ;;
    --model)
      CLAUDE_ARGS+=("--model" "$2")
      shift 2
      ;;
    --effort)
      CLAUDE_ARGS+=("--effort" "$2")
      shift 2
      ;;
    --non-interactive)
      # In non-interactive mode, bypass permission prompts
      CLAUDE_ARGS+=("-p" "--dangerously-skip-permissions")
      shift
      ;;
    *)
      shift
      ;;
  esac
done

if [[ -z "$PROMPT" ]]; then
  echo "Error: No prompt provided to delegate-to-claude.sh" >&2
  exit 1
fi

# Execute Claude directly
exec claude "${CLAUDE_ARGS[@]}" "$PROMPT"
