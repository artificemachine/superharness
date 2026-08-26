#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHONPATH="${SRC_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# Keep caller overrides first; append launchd-safe fallback locations.
export PATH="${PATH:-}:/Applications/cmux.app/Contents/Resources/bin:/opt/homebrew/bin:${HOME}/.local/bin:${HOME}/.nvm/versions/node/v25.2.1/bin:${HOME}/.pyenv/shims:${HOME}/.pyenv/bin:/usr/local/bin:/usr/bin:/bin"

PYTHON_BIN="${SUPERHARNESS_PYTHON:-python3}"
exec "$PYTHON_BIN" -m superharness.engine.pi_runtime "$@"
