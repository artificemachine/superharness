#!/bin/bash
set -euo pipefail

# Ensure the hermes binary is findable under launchd's stripped PATH.
# Inherited PATH goes first so a caller-provided override always wins.
export PATH="${PATH:-}:/Applications/cmux.app/Contents/Resources/bin:/opt/homebrew/bin:${HOME}/.local/bin:${HOME}/.nvm/versions/node/v25.2.1/bin:${HOME}/.pyenv/shims:${HOME}/.pyenv/bin:/usr/local/bin:/usr/bin:/bin"

usage() {
  cat <<'EOF'
Usage: delegate-to-hermes.sh --prompt TEXT [--project DIR] [--model ID]
                             [--effort none|minimal|low|medium|high|xhigh|max|ultra]
                             [--yolo] [--non-interactive]

Runs one Hermes Agent turn (`hermes chat -Q --query-file -`). The prompt is sent
on stdin so quotes, $(...) and backticks are never shell-interpreted.
EOF
}

HERMES_ARGS=(chat -Q --query-file -)
PROMPT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --project)
      cd "$2"
      shift 2
      ;;
    --prompt)
      PROMPT="$2"
      shift 2
      ;;
    --model)
      HERMES_ARGS+=(-m "$2")
      shift 2
      ;;
    --effort)
      case "$2" in
        none|minimal|low|medium|high|xhigh|max|ultra) ;;
        *)
          echo "Error: unsupported effort '$2' for hermes" >&2
          exit 2
          ;;
      esac
      HERMES_ARGS+=(--reasoning "$2")
      shift 2
      ;;
    --yolo)
      HERMES_ARGS+=(--yolo)
      shift
      ;;
    *)
      # --non-interactive is implied by -Q; --codex-bypass is codex-specific.
      shift
      ;;
  esac
done

if [[ -z "$PROMPT" ]]; then
  echo "Error: No prompt provided to delegate-to-hermes.sh" >&2
  exit 1
fi

if ! command -v hermes >/dev/null 2>&1; then
  echo "Error: hermes binary not found on PATH" >&2
  exit 127
fi

# API keys kept in the macOS Keychain as generic passwords named `env:<VAR>`
# (account: $HERMES_KEYCHAIN_ACCOUNT, default $USER) are exported to hermes by
# environment only: never on a command line, in a file, or in any output. A
# variable already set by the caller wins. A failed lookup is reported and
# hermes then falls back to its own config (~/.hermes/.env).
KEYCHAIN_ENV_VARS=(DEEPSEEK_API_KEY)
if command -v security >/dev/null 2>&1; then
  for var in "${KEYCHAIN_ENV_VARS[@]}"; do
    [[ -n "${!var:-}" ]] && continue
    if kc_value="$(security find-generic-password -a "${HERMES_KEYCHAIN_ACCOUNT:-${USER:-}}" -s "env:${var}" -w 2>/dev/null)" && [[ -n "$kc_value" ]]; then
      export "${var}=${kc_value}"
    else
      echo "Warning: no usable Keychain entry env:${var}; ${var} left to hermes config" >&2
    fi
  done
  unset kc_value
fi

printf '%s' "$PROMPT" | exec hermes "${HERMES_ARGS[@]}"
