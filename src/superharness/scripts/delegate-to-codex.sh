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

# Fast-path: print usage and exit before touching codex binary
for arg in "$@"; do
  if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
    echo "Usage: delegate-to-codex.sh [--project DIR] [--task ID] [--prompt TEXT] [--model MODEL] [--plan-only] [--non-interactive]"
    echo "Delegates a superharness task to the Codex CLI agent."
    exit 0
  fi
done

exec "$PYTHON3" -m superharness.commands.delegate --to codex-cli "$@"
