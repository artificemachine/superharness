#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHONPATH="${SRC_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# Ensure agent binaries are findable under launchd's stripped PATH
export PATH="/Applications/cmux.app/Contents/Resources/bin:${HOME}/.local/bin:${HOME}/.nvm/versions/node/v25.2.1/bin:${HOME}/.pyenv/shims:${HOME}/.pyenv/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

# Build Codex CLI command
MODEL_ARGS=()
PROMPT=""
PROJECT_DIR="."
NON_INTERACTIVE=0
BYPASS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT_DIR="$2"
      shift 2
      ;;
    --prompt)
      PROMPT="$2"
      shift 2
      ;;
    --model)
      MODEL_ARGS+=("--model" "$2")
      shift 2
      ;;
    --effort)
      # Map superharness effort to codex config override
      _eff="$2"
      if [[ "$_eff" == "max" ]]; then
        _eff="xhigh"
      fi
      MODEL_ARGS+=("-c" "model_reasoning_effort=\"$_eff\"")
      shift 2
      ;;
    --non-interactive)
      NON_INTERACTIVE=1
      shift
      ;;
    --codex-bypass)
      BYPASS=1
      shift
      ;;
    *)
      shift
      ;;
  esac
done

if [[ -z "$PROMPT" ]]; then
  echo "Error: No prompt provided to delegate-to-codex.sh" >&2
  exit 1
fi

if [[ $NON_INTERACTIVE -eq 1 ]]; then
  # Build execution command with automation flags
  CODEX_ARGS=("exec" "--skip-git-repo-check" "-C" "$PROJECT_DIR")
  CODEX_ARGS+=("${MODEL_ARGS[@]}")
  
  if [[ $BYPASS -eq 1 ]]; then
    CODEX_ARGS+=("--dangerously-bypass-approvals-and-sandbox")
  else
    CODEX_ARGS+=("--full-auto")
  fi
  
  exec codex "${CODEX_ARGS[@]}" "$PROMPT"
else
  # Regular interactive session
  exec codex -C "$PROJECT_DIR" "${MODEL_ARGS[@]}" "$PROMPT"
fi
