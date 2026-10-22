#!/usr/bin/env bash
# scripts/ci/run-gate.sh — allowlisted dispatcher for the gate commands this
# project's .github/workflows/ci.yml and .gitlab-ci.yml both run.
#
# A gate's actual command lives in exactly one place (this file's case
# statement), so the two CI providers differ only in provider-specific
# policy around it: images, checkout depth, permissions, triggers, and cache
# config.
#
# Run from the project root. Reads no credentials or secrets.
#
# Usage: scripts/ci/run-gate.sh <gate>
#        scripts/ci/run-gate.sh --help
set -euo pipefail

usage() {
  printf '%s\n' \
    "Usage: $(basename "$0") <gate>" \
    "" \
    "Allowlisted gates:" \
    "  doctrine    bash tests/doctrine/doctrine-guard.sh" \
    "  shipguard   shipguard scan . --severity medium"
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
  exit 0
fi

if [ $# -ne 1 ]; then
  echo "error: expected exactly one gate name, got $#" >&2
  usage >&2
  exit 1
fi

gate="$1"

# Explicit allowlist, no fallback: an unrecognized or unset gate must fail
# loudly rather than silently no-op or run something unexpected.
case "$gate" in
  doctrine)
    bash tests/doctrine/doctrine-guard.sh
    ;;
  shipguard)
    shipguard scan . --severity medium
    ;;
  *)
    echo "error: unknown gate '${gate}'" >&2
    usage >&2
    exit 1
    ;;
esac
