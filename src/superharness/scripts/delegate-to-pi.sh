#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHONPATH="${SRC_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# Ensure agent binaries are findable under launchd/systemd stripped PATH.
# Inherited PATH goes first so a caller-provided override always wins.
export PATH="${PATH:-}:/usr/local/bin:${HOME}/.local/bin:/usr/bin:/bin"

# pi is the canonical agent harness (OpenCode decommissioned 2026-07-07).
# Headless one-shot: -p prints and exits, --no-session keeps it ephemeral.
# RMDI model refs (e.g. vm903-sidecar/qwen3.6-27b-awq) are pi-native — the
# pi extension registers the fleet providers, no prefix translation needed.
PI_ARGS=("-p" "--no-session")
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
      PI_ARGS+=("--model" "$2")
      shift 2
      ;;
    *)
      # --non-interactive/--yolo/--effort: pi -p is already non-interactive;
      # effort maps to pi thinking levels only interactively — ignored here.
      shift
      ;;
  esac
done

if [[ -z "$PROMPT" ]]; then
  echo "Error: No prompt provided to delegate-to-pi.sh" >&2
  exit 1
fi

exec pi "${PI_ARGS[@]}" "$PROMPT"
