#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHONPATH="${SRC_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# Ensure agent binaries are findable under launchd's stripped PATH
export PATH="/Applications/cmux.app/Contents/Resources/bin:/opt/homebrew/bin:${HOME}/.local/bin:${HOME}/.nvm/versions/node/v25.2.1/bin:${HOME}/.pyenv/shims:${HOME}/.pyenv/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

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

# Fast-path: print usage and exit before touching opencode binary
for arg in "$@"; do
  if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
    echo "Usage: delegate-to-opencode.sh [--project DIR] [--task ID] [--prompt TEXT] [--model MODEL] [--plan-only] [--non-interactive]"
    echo "Delegates a superharness task to the OpenCode CLI agent."
    exit 0
  fi
done

# Delegate to the Python `superharness delegate` command which builds the
# proper prompt from task context. Same shape as claude/codex/gemini adapters.
exec "$PYTHON3" -m superharness.commands.delegate --to opencode "$@"
