#!/usr/bin/env bash
# Required-check gate shared by the release, publish, and candidate workflows.
#
# Fails closed unless every check main's branch protection requires is green
# on the given commit. Single source of truth for the REQUIRED list: the
# release.yml, publish.yml, and candidate.yml gates must assert the same
# check names, so the lookup lives here once (release-candidate rollout
# refactor, iteration 2).
#
# Usage: required_checks_gate.sh <full-or-resolvable-commit-sha>
# Env:   GH_TOKEN must be set (workflows pass secrets.GITHUB_TOKEN).
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <commit-sha>" >&2
  exit 64
fi

SHA="$1"
REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"

# Keep in sync with branch protection on main:
#   gh api repos/${GITHUB_REPOSITORY}/branches/main/protection \
#     --jq '.required_status_checks.contexts'
REQUIRED=("QA Gate" "Windows-Native Release Gate" "ShipGuard Scan" "Gitleaks")

gh api "repos/${REPO}/commits/${SHA}/check-runs?per_page=100" \
  --paginate --jq '.check_runs[] | {name, conclusion, started_at}' \
  | jq -s '.' > /tmp/check_runs.json

echo "Found $(jq 'length' /tmp/check_runs.json) check run(s) on ${SHA}"

FAILED=0
for name in "${REQUIRED[@]}"; do
  # A rerun creates a second check run with the same name — take the
  # most recently started one, which is the authoritative result.
  conclusion="$(jq -r --arg n "$name" \
    '[.[] | select(.name == $n)] | sort_by(.started_at) | last | .conclusion // "MISSING"' \
    /tmp/check_runs.json)"
  if [ "$conclusion" = "success" ]; then
    echo "  OK       ${name}: success"
  elif [ "$conclusion" = "MISSING" ] || [ "$conclusion" = "null" ]; then
    echo "  BLOCKED  ${name}: no check run found on ${SHA}"
    FAILED=1
  else
    echo "  BLOCKED  ${name}: ${conclusion}"
    FAILED=1
  fi
done

if [ "$FAILED" -ne 0 ]; then
  echo ""
  echo "Refusing to proceed on ${SHA} — required checks are not green."
  echo "Re-run CI on this commit rather than bypassing this gate."
  exit 1
fi

echo ""
echo "All required checks green on ${SHA} — proceeding."
