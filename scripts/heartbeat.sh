#!/bin/bash
# heartbeat.sh — Run proactive checks for superharness watcher
# Called by inbox-watch.sh after each dispatch pass
# Security: check IDs map to hardcoded commands — heartbeat.yaml 'command' field is ignored
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  heartbeat.sh --project DIR

Options:
  -p, --project DIR   Project directory containing .superharness/
  -h, --help          Show this help message and exit

Runs proactive checks defined in .superharness/heartbeat.yaml.
State is persisted in .superharness/heartbeat-state.yaml.

Security: The 'command:' field in heartbeat.yaml is documentation only.
Unknown check IDs are logged and skipped — never executed.
USAGE
}

PROJECT_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[ -n "$PROJECT_DIR" ] || { echo "--project is required" >&2; exit 2; }

SH_DIR="$PROJECT_DIR/.superharness"
HB_CONFIG="$SH_DIR/heartbeat.yaml"
HB_STATE="$SH_DIR/heartbeat-state.yaml"

# Silently exit if no heartbeat config (optional feature)
if [ ! -f "$HB_CONFIG" ]; then
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

NOW_EPOCH="$(date +%s)"

# ---------------------------------------------------------------------------
# read_yaml_field FILE KEY
# Returns the scalar value for a simple "key: value" line in a YAML file.
# Used for flat state file reads. Returns empty string if not found.
# ---------------------------------------------------------------------------
read_state_field() {
  local file="$1"
  local check_id="$2"
  local field="$3"
  # Match "check_id:" block then find "  field: value"
  python3 - "$file" "$check_id" "$field" << 'PY'
import sys, pathlib
fpath, check_id, field = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    import yaml
    data = yaml.safe_load(pathlib.Path(fpath).read_text()) or {}
    val = (data.get(check_id) or {}).get(field, "")
    print(val if val != "" else "")
except Exception:
    print("")
PY
}

# ---------------------------------------------------------------------------
# update_state CHECK_ID FIELD VALUE
# Writes/updates a field in the flat heartbeat-state.yaml
# ---------------------------------------------------------------------------
update_state() {
  local check_id="$1"
  local field="$2"
  local value="$3"
  python3 - "$HB_STATE" "$check_id" "$field" "$value" << 'PY'
import sys, pathlib

fpath, check_id, field, value = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
p = pathlib.Path(fpath)
try:
    import yaml
    data = yaml.safe_load(p.read_text()) if p.exists() else {}
    data = data or {}
except Exception:
    data = {}

if check_id not in data or not isinstance(data[check_id], dict):
    data[check_id] = {}
try:
    data[check_id][field] = int(value)
except ValueError:
    data[check_id][field] = value

# Emit minimal YAML (no block markers, simple scalars)
lines = []
for cid, fields in data.items():
    lines.append(f"{cid}:")
    for k, v in fields.items():
        lines.append(f"  {k}: {v}")
p.write_text("\n".join(lines) + "\n")
PY
}

# ---------------------------------------------------------------------------
# run_idle_warning
# Check if ledger.md has had any activity in the last 48 hours.
# ---------------------------------------------------------------------------
run_idle_warning() {
  local ledger="$SH_DIR/ledger.md"
  if [ ! -f "$ledger" ]; then
    echo "heartbeat: idle-warning: no ledger.md found"
    return 0
  fi
  # Get the mtime of ledger.md in epoch seconds
  local ledger_mtime
  if stat -f %m "$ledger" >/dev/null 2>&1; then
    ledger_mtime="$(stat -f %m "$ledger")"
  elif stat -c %Y "$ledger" >/dev/null 2>&1; then
    ledger_mtime="$(stat -c %Y "$ledger")"
  else
    ledger_mtime=0
  fi
  local age_seconds=$(( NOW_EPOCH - ledger_mtime ))
  local threshold=$(( 48 * 3600 ))
  if [ "$age_seconds" -gt "$threshold" ]; then
    echo "heartbeat: idle-warning: no ledger activity in $(( age_seconds / 3600 ))h (threshold: 48h)"
  fi
}

# ---------------------------------------------------------------------------
# ALLOWLIST: maps check id -> vetted command runner function or inline command
# The 'command:' field in heartbeat.yaml is NEVER read or executed.
# ---------------------------------------------------------------------------
run_check_by_id() {
  local check_id="$1"
  case "$check_id" in
    stale-recovery)
      bash "$ROOT_DIR/scripts/inbox-recover-stale.sh" \
        --project "$PROJECT_DIR" \
        --timeout-minutes 30 \
        --action stale || true
      ;;
    idle-warning)
      run_idle_warning
      ;;
    hygiene-check)
      bash "$ROOT_DIR/scripts/check-contract-hygiene.sh" \
        --project "$PROJECT_DIR" || true
      ;;
    *)
      # Unknown ID: log and skip — NEVER execute
      echo "heartbeat: unknown check id '$check_id', skipping"
      return 1
      ;;
  esac
}

# ---------------------------------------------------------------------------
# Main: read checks from heartbeat.yaml and run eligible ones
# ---------------------------------------------------------------------------
# Process checks in bash; read via python in process substitution to avoid subshell issues
while IFS='|' read -r check_id enabled interval_minutes; do
  [ -n "$check_id" ] || continue

  # Skip disabled checks
  if [ "$enabled" != "True" ] && [ "$enabled" != "true" ]; then
    continue
  fi

  # Look up last_run from state
  last_run=0
  if [ -f "$HB_STATE" ]; then
    last_run_val="$(read_state_field "$HB_STATE" "$check_id" "last_run")"
    if [[ "$last_run_val" =~ ^[0-9]+$ ]]; then
      last_run="$last_run_val"
    fi
  fi

  # Check if interval has elapsed
  interval_seconds=$(( interval_minutes * 60 ))
  elapsed=$(( NOW_EPOCH - last_run ))
  if [ "$elapsed" -lt "$interval_seconds" ]; then
    continue
  fi

  # Run the vetted command for this id
  echo "heartbeat: running check '$check_id'"
  if run_check_by_id "$check_id"; then
    update_state "$check_id" "last_run" "$NOW_EPOCH"
  else
    # Unknown ID — already logged inside run_check_by_id; do not update state
    true
  fi

done < <(python3 - "$HB_CONFIG" << 'PY'
import sys, pathlib, yaml
cfg = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text()) or {}
checks = cfg.get("checks", [])
for c in checks:
    parts = [
        str(c.get("id", "")),
        str(c.get("enabled", False)),
        str(c.get("interval_minutes", 0)),
    ]
    print("|".join(parts))
PY
)
