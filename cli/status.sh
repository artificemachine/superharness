#!/bin/bash
# cli/status.sh — superharness project status dashboard
# Shows contract, tasks, watcher, and profile at a glance.
# Usage: cli/status.sh [--project DIR]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(cat "$SCRIPT_DIR/../VERSION" 2>/dev/null | tr -d '[:space:]')"
VERSION="${VERSION:-0.7.0}"

PROJECT_DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --project|-p)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: status.sh [--project DIR]"
      echo ""
      echo "Show project dashboard: contract, tasks, watcher, and profile."
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

[ -z "$PROJECT_DIR" ] && PROJECT_DIR="$(pwd)"
PROJECT_DIR="$(cd "$PROJECT_DIR" 2>/dev/null && pwd)" || { echo "Not a valid directory: $PROJECT_DIR" >&2; exit 1; }

SH_DIR="$PROJECT_DIR/.superharness"
CONTRACT="$SH_DIR/contract.yaml"
LEDGER="$SH_DIR/ledger.md"
HEARTBEAT="$SH_DIR/watcher.heartbeat"
PROFILE="$SH_DIR/profile.yaml"

# ---------------------------------------------------------------------------
# Parse contract.yaml with Ruby
# ---------------------------------------------------------------------------

HAS_CONTRACT=0
if [ -f "$CONTRACT" ]; then
  CONTRACT_INFO="$(ruby - "$CONTRACT" <<'RUBY'
require "yaml"
require "date"

begin
  data = YAML.safe_load(File.read(ARGV[0]), permitted_classes: [Date])
rescue => e
  data = {}
end
data ||= {}

contract_id     = data["id"]     || "(unknown)"
contract_status = data["status"] || "unknown"
goal            = data["goal"]   || "TBD"
tasks           = Array(data["tasks"])

pending  = tasks.count { |t| t.is_a?(Hash) && t["status"] == "todo" }
running  = tasks.count { |t| t.is_a?(Hash) && t["status"] == "in_progress" }
done_cnt = tasks.count { |t| t.is_a?(Hash) && t["status"] == "done" }
failed   = tasks.count { |t| t.is_a?(Hash) && t["status"] == "failed" }

next_task  = tasks.find { |t| t.is_a?(Hash) && t["status"] == "todo" }
next_id    = next_task ? (next_task["id"]    || "") : ""
next_owner = next_task ? (next_task["owner"] || "") : ""

puts contract_id
puts contract_status
puts goal
puts pending
puts running
puts done_cnt
puts failed
puts next_id
puts next_owner
RUBY
  )"
  _contract_id="$(     printf '%s\n' "$CONTRACT_INFO" | sed -n '1p')"
  _contract_status="$( printf '%s\n' "$CONTRACT_INFO" | sed -n '2p')"
  _goal="$(            printf '%s\n' "$CONTRACT_INFO" | sed -n '3p')"
  _pending="$(         printf '%s\n' "$CONTRACT_INFO" | sed -n '4p')"
  _running="$(         printf '%s\n' "$CONTRACT_INFO" | sed -n '5p')"
  _done="$(            printf '%s\n' "$CONTRACT_INFO" | sed -n '6p')"
  _failed="$(          printf '%s\n' "$CONTRACT_INFO" | sed -n '7p')"
  _next_id="$(         printf '%s\n' "$CONTRACT_INFO" | sed -n '8p')"
  _next_owner="$(      printf '%s\n' "$CONTRACT_INFO" | sed -n '9p')"
  HAS_CONTRACT=1
fi

# ---------------------------------------------------------------------------
# Last non-empty, non-comment ledger entry
# ---------------------------------------------------------------------------

LAST_ACTIVITY="(none)"
if [ -f "$LEDGER" ]; then
  _last="$(grep -v '^\s*#' "$LEDGER" 2>/dev/null | grep -v '^\s*$' | tail -1 || true)"
  [ -n "$_last" ] && LAST_ACTIVITY="$_last"
fi

# ---------------------------------------------------------------------------
# Watcher heartbeat
# ---------------------------------------------------------------------------

WATCHER_STATUS="unknown (run superharness doctor)"
if [ -f "$HEARTBEAT" ]; then
  _now="$(date +%s)"
  _mtime="$(ruby -e "puts File.mtime(ARGV[0]).to_i" "$HEARTBEAT" 2>/dev/null || echo 0)"
  _age=$(( _now - _mtime ))
  if [ "$_age" -le 90 ]; then
    WATCHER_STATUS="running"
  else
    WATCHER_STATUS="stale"
  fi
fi

# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

PROFILE_LINE="(default — no profile.yaml)"
if [ -f "$PROFILE" ]; then
  PROFILE_INFO="$(ruby - "$PROFILE" <<'RUBY'
require "yaml"
require "date"
begin
  data = YAML.safe_load(File.read(ARGV[0]), permitted_classes: [Date])
rescue
  data = {}
end
data ||= {}
puts data["autonomy"]      || ""
puts data["primary_agent"] || ""
puts data["team_size"]     || ""
RUBY
  )"
  _p_autonomy="$( printf '%s\n' "$PROFILE_INFO" | sed -n '1p')"
  _p_agent="$(    printf '%s\n' "$PROFILE_INFO" | sed -n '2p')"
  _p_team="$(     printf '%s\n' "$PROFILE_INFO" | sed -n '3p')"
  PROFILE_LINE="${_p_autonomy} · ${_p_agent} · ${_p_team}"
fi

# ---------------------------------------------------------------------------
# Project name
# ---------------------------------------------------------------------------

PROJECT_NAME="$(basename "$PROJECT_DIR")"

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

echo "superharness v${VERSION} — ${PROJECT_NAME}"
echo "=================================="

if [ "$HAS_CONTRACT" -eq 1 ]; then
  echo "Contract: ${_contract_id} (${_contract_status})"
  echo "Goal:     ${_goal}"
  echo ""
  echo "Tasks:  ${_pending} pending · ${_running} running · ${_done} done · ${_failed} failed"
  if [ -n "${_next_id:-}" ]; then
    if [ -n "${_next_owner:-}" ]; then
      echo "        Next: ${_next_id} (${_next_owner})"
    else
      echo "        Next: ${_next_id}"
    fi
  fi
else
  echo "Contract: (none — run superharness init)"
fi

echo ""
echo "Last activity: ${LAST_ACTIVITY}"
echo "Watcher:       ${WATCHER_STATUS}"
echo "Profile:       ${PROFILE_LINE}"
