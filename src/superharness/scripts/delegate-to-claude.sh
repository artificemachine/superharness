#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHONPATH="${SRC_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

resolve_python() {
  if [[ -n "${SUPERHARNESS_PYTHON:-}" ]]; then
    echo "${SUPERHARNESS_PYTHON}"
    return
  fi

  local shux_bin shebang candidate resolved
  shux_bin="$(command -v shux 2>/dev/null || true)"
  if [[ -n "$shux_bin" && -r "$shux_bin" ]]; then
    IFS= read -r shebang < "$shux_bin" || true
    if [[ "$shebang" == '#!'*python* ]]; then
      candidate="${shebang#\#!}"
      if [[ "$candidate" == "/usr/bin/env "* ]]; then
        candidate="${candidate#"/usr/bin/env "}"
        candidate="${candidate%% *}"
        resolved="$(command -v "$candidate" 2>/dev/null || true)"
        if [[ -n "$resolved" ]]; then
          echo "$resolved"
          return
        fi
      elif [[ -x "$candidate" ]]; then
        echo "$candidate"
        return
      fi
    fi
  fi

  echo "python3"
}

PYTHON3="$(resolve_python)"

# Build Claude CLI command
CLAUDE_ARGS=()
PROMPT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      # Claude uses current directory as project root
      cd "$2"
      shift 2
      ;;
    --prompt)
      PROMPT="$2"
      shift 2
      ;;
    --yolo)
      # Map to Claude's dangerously-skip-permissions
      CLAUDE_ARGS+=("--dangerously-skip-permissions")
      shift
      ;;
    --plan-only)
      # In newer Claude CLI versions, plan mode is a subcommand or positional arg
      # but providing a prompt in a clean dir usually defaults to planning.
      shift
      ;;
    --non-interactive)
      # Handled by passing prompt as positional arg
      shift
      ;;
    *)
      # Ignore other Superharness-specific flags
      shift
      ;;
  esac
done

# Launch Claude
exec claude "${CLAUDE_ARGS[@]}" "$PROMPT"
