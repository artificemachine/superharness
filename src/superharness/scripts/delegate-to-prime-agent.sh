#!/bin/bash
# UNVERIFIED — prime-agent adapter (PLAN-prime-agent-adoptions.md Iteration 6,
# Resolution 1, binding). prime-agent's non-interactive CLI flags have never
# been probed against an installed binary. This script exists ONLY so the
# manifest's `launcher_script` field satisfies
# tests/contract/test_manifest_compliance.py (every manifest must declare a
# launcher_script that exists on disk) — it deliberately does not attempt to
# build or run a real prime-agent invocation. Dispatch must stay disabled
# until someone probes a real binary and replaces this stub with a verified
# implementation (mirroring delegate-to-codex.sh / delegate-to-gemini.sh).
set -euo pipefail

# Fast-path: print usage and exit 0 before refusing — mirrors
# delegate-to-gemini.sh's `--help`/`-h` fast-path so the CI shell-entrypoint
# smoke test (`bash "$entrypoint" --help`) stays green for this script too.
for arg in "$@"; do
  if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
    echo "Usage: delegate-to-prime-agent.sh [--project DIR] [--task ID] [--prompt TEXT] [--model MODEL] [--plan-only] [--non-interactive]"
    echo "EXPERIMENTAL / UNVERIFIED: prime-agent adapter — dispatch is intentionally disabled."
    echo "See src/superharness/adapter_manifests/prime-agent.yaml."
    exit 0
  fi
done

echo "prime-agent adapter is experimental and UNVERIFIED — dispatch is intentionally disabled (see src/superharness/adapter_manifests/prime-agent.yaml). Refusing to run." >&2
exit 1
