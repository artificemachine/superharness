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
# Build Gemini CLI command
GEMINI_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      # Gemini uses the current working directory as the project root
      # No explicit --project flag, but we should cd there
      cd "$2"
      shift 2
      ;;
    --task)
      # Task ID is not directly supported by Gemini CLI positional args
      # but we can pass it as context in the prompt
      shift 2
      ;;
    --prompt)
      GEMINI_ARGS+=("--prompt" "$2")
      shift 2
      ;;
    --model)
      GEMINI_ARGS+=("--model" "$2")
      shift 2
      ;;
    --plan-only)
      GEMINI_ARGS+=("--approval-mode" "plan")
      shift
      ;;
    --non-interactive)
      # Gemini uses --prompt to trigger headless mode
      shift
      ;;
    *)
      # Ignore other Superharness-specific flags for now
      shift
      ;;
  esac
done

# Launch Gemini
exec gemini "${GEMINI_ARGS[@]}"
