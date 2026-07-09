#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHONPATH="${SRC_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# Ensure agent binaries are findable under launchd's stripped PATH.
# Inherited PATH goes first so a caller-provided override (tests, CI, custom
# installs) always wins; these are fallback dirs for when PATH is empty/minimal.
export PATH="${PATH:-}:/Applications/cmux.app/Contents/Resources/bin:${HOME}/.local/bin:${HOME}/.nvm/versions/node/v25.2.1/bin:${HOME}/.pyenv/shims:${HOME}/.pyenv/bin:/usr/local/bin:/usr/bin:/bin"

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

# Fast-path: print usage and exit before touching gemini binary
for arg in "$@"; do
  if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
    echo "Usage: delegate-to-gemini.sh [--project DIR] [--task ID] [--prompt TEXT] [--model MODEL] [--plan-only] [--non-interactive]"
    echo "Delegates a superharness task to the Gemini CLI agent."
    exit 0
  fi
done

# Build Gemini CLI command
GEMINI_ARGS=()
PROMPT=""

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
      # Pass the prompt as a positional argument at the end
      PROMPT="$2"
      shift 2
      ;;
    --yolo)
      GEMINI_ARGS+=("-y" "--skip-trust")
      shift
      ;;
    --plan-only)
      GEMINI_ARGS+=("--approval-mode" "plan")
      shift
      ;;
    --non-interactive)
      # Non-interactive mode in Gemini CLI is triggered by providing a prompt
      GEMINI_ARGS+=("--skip-trust")
      shift
      ;;
    --model)
      GEMINI_ARGS+=("--model" "$2")
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

# Preflight: validate GEMINI.md exists and contains required protocol sections.
# Gemini CLI reads GEMINI.md at startup (like Claude reads CLAUDE.md) for
# self-orientation. Without it, the agent has no task protocol and will stall.
_gemini_md="$(pwd)/GEMINI.md"
if [[ ! -f "$_gemini_md" ]]; then
  _msg="PREFLIGHT FAIL: GEMINI.md not found at $_gemini_md — run '/init' inside Gemini CLI (or 'gemini /init' from terminal) in the project root to generate it, then redispatch."
  echo "$_msg" | tee -a /tmp/shux-launcher-error.log >&2
  exit 1
fi
_missing_sections=()
for _pattern in "contract\.yaml|\.superharness|shux contract" "report_ready" "superharness|shux"; do
  if ! grep -qE "$_pattern" "$_gemini_md"; then
    _missing_sections+=("$_pattern")
  fi
done
if [[ ${#_missing_sections[@]} -gt 0 ]]; then
  _msg="PREFLIGHT FAIL: GEMINI.md at $_gemini_md is missing required content: ${_missing_sections[*]} — regenerate with '/init' inside Gemini CLI or update GEMINI.md manually."
  echo "$_msg" | tee -a /tmp/shux-launcher-error.log >&2
  exit 1
fi

# Launch Gemini with the prompt as the final argument.
# Do NOT pipe printf/stdin into gemini: piping closes stdin after writing,
# which sends EOF (^D) to gemini immediately and causes it to exit before
# processing the task. Trust is bypassed via --skip-trust in GEMINI_ARGS.
# Gemini requires at least one user message to start (exits 42 otherwise).
# When no explicit prompt is given, use a bootstrap directive — GEMINI.md
# contains the full protocol so Gemini can self-orient from there.
if [[ -z "$PROMPT" ]]; then
  PROMPT="Read GEMINI.md for the full task protocol. Find your task in .superharness/contract.yaml (owner: gemini-cli, status: todo or plan_approved) and begin."
fi
# Retry once on transient network failures (ETIMEDOUT, ECONNRESET) before
# giving up. Gemini calls cloudcode-pa.googleapis.com which can hiccup.
_attempt() {
  gemini ${GEMINI_ARGS[@]+"${GEMINI_ARGS[@]}"} "$PROMPT" < /dev/null
}
if _attempt; then
  exit 0
fi
_rc=$?
echo "Gemini launch failed (rc=$_rc), retrying once after 10s..." >> /tmp/shux-launcher-error.log
sleep 10
exec gemini ${GEMINI_ARGS[@]+"${GEMINI_ARGS[@]}"} "$PROMPT" < /dev/null || {
  echo "Gemini launch failed twice (rc=$?)" >> /tmp/shux-launcher-error.log
  exit 1
}
