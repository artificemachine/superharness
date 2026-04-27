#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHONPATH="${SRC_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# Ensure agent binaries are findable under launchd's stripped PATH
export PATH="/Applications/cmux.app/Contents/Resources/bin:${HOME}/.local/bin:${HOME}/.nvm/versions/node/v25.2.1/bin:${HOME}/.pyenv/shims:${HOME}/.pyenv/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

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

# Fast-path: print usage and exit before touching claude binary
for arg in "$@"; do
  if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
    echo "Usage: delegate-to-claude.sh [--project DIR] [--task ID] [--prompt TEXT] [--model MODEL] [--plan-only] [--non-interactive]"
    echo "Delegates a superharness task to the Claude Code CLI agent."
    exit 0
  fi
done

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
