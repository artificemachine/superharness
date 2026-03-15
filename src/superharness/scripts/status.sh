#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  status.sh [--project DIR] [--retry-threshold N] [--check]

Options:
  -p, --project DIR      Project directory containing .superharness/ (default: current dir)
      --retry-threshold N  Alert threshold for retry_count (default: 3)
      --check            Exit non-zero when issues are detected
  -h, --help             Show this help message and exit
USAGE
}

PYTHON3="${SUPERHARNESS_PYTHON:-python3}"
PROJECT_DIR="$(pwd)"
RETRY_THRESHOLD=3
CHECK_MODE=0

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --retry-threshold)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      RETRY_THRESHOLD="$2"
      shift 2
      ;;
    --check)
      CHECK_MODE=1
      shift
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

case "$RETRY_THRESHOLD" in
  ''|*[!0-9]*|0)
    echo "--retry-threshold must be a positive integer" >&2
    exit 2
    ;;
esac

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Project directory does not exist: $PROJECT_DIR" >&2
  exit 1
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
HARNESS_DIR="$PROJECT_DIR/.superharness"

if [ ! -d "$HARNESS_DIR" ]; then
  echo "Missing .superharness in project: $PROJECT_DIR" >&2
  exit 1
fi

INBOX_FILE="$HARNESS_DIR/inbox.yaml"
HANDOFF_DIR="$HARNESS_DIR/handoffs"
DISCUSSIONS_DIR="$HARNESS_DIR/discussions"
PLATFORM="$(uname -s)"

watcher_level="warn"
watcher_msg=""
if [ "$PLATFORM" = "Darwin" ]; then
  slug="$(basename "$PROJECT_DIR" | tr -cs 'A-Za-z0-9' '-')"
  label="com.superharness.inbox.${slug}"
  if launchctl_out="$(launchctl print "gui/$(id -u)/$label" 2>/dev/null)"; then
    state="$(printf '%s\n' "$launchctl_out" | sed -n 's/^[[:space:]]*state = //p' | head -n1)"
    last_exit="$(printf '%s\n' "$launchctl_out" | sed -n 's/^[[:space:]]*last exit code = //p' | head -n1)"
    run_interval="$(printf '%s\n' "$launchctl_out" | sed -n 's/^[[:space:]]*run interval = \([0-9][0-9]*\).*/\1/p' | head -n1)"
    if [ "$state" = "running" ] || [ "$state" = "active" ]; then
      watcher_level="ok"
      watcher_msg="loaded state=$state interval=${run_interval:-unknown}s exit=${last_exit:-unknown}"
    elif [ "$state" = "not running" ] && { [ "$last_exit" = "0" ] || [ "$last_exit" = "(never exited)" ]; }; then
      watcher_level="ok"
      watcher_msg="loaded idle interval=${run_interval:-unknown}s"
    else
      watcher_level="warn"
      watcher_msg="loaded state=${state:-unknown} exit=${last_exit:-unknown}"
    fi
  else
    watcher_level="bad"
    watcher_msg="not loaded"
  fi
elif [ "$PLATFORM" = "Linux" ] && command -v systemctl >/dev/null 2>&1; then
  unit="superharness-watcher@$(basename "$PROJECT_DIR").service"
  active="$(systemctl --user is-active "$unit" 2>/dev/null || true)"
  if [ "$active" = "active" ]; then
    watcher_level="ok"
    watcher_msg="systemd unit active ($unit)"
  elif [ -n "$active" ]; then
    watcher_level="warn"
    watcher_msg="systemd unit $unit is $active"
  else
    watcher_level="warn"
    watcher_msg="systemd unit $unit not found"
  fi
else
  watcher_level="warn"
  watcher_msg="no launchd/systemd watcher check available on $PLATFORM"
fi

# Check watcher heartbeat
HEARTBEAT_FILE="$HARNESS_DIR/watcher.heartbeat"
HEARTBEAT_STALE_SECONDS=120  # 2x default poll interval
heartbeat_status="missing"
heartbeat_detail="no heartbeat file"
if [ -f "$HEARTBEAT_FILE" ]; then
  HB_TS="$(head -n1 "$HEARTBEAT_FILE" | tr -d '[:space:]')"
  if [ -n "$HB_TS" ]; then
    HB_EPOCH="$(date -juf "%Y-%m-%dT%H:%M:%SZ" "$HB_TS" +%s 2>/dev/null || date -d "$HB_TS" +%s 2>/dev/null || echo 0)"
    NOW_EPOCH="$(date +%s)"
    if [ "$HB_EPOCH" -gt 0 ] 2>/dev/null; then
      AGE=$(( NOW_EPOCH - HB_EPOCH ))
      AGE_MIN=$(( AGE / 60 ))
      if [ "$AGE" -ge "$HEARTBEAT_STALE_SECONDS" ]; then
        heartbeat_status="stale"
        heartbeat_detail="last heartbeat ${AGE_MIN}m ago"
      else
        heartbeat_status="ok"
        heartbeat_detail="last heartbeat ${AGE}s ago"
      fi
    fi
  fi
fi

stats="$(
  "$PYTHON3" - "$INBOX_FILE" "$HANDOFF_DIR" "$DISCUSSIONS_DIR" "$RETRY_THRESHOLD" <<'PY'
import sys, yaml, os, glob as glob_mod
inbox_file, handoff_dir, discussions_dir, retry_threshold = sys.argv[1:5]
threshold = int(retry_threshold) if retry_threshold.isdigit() and int(retry_threshold) > 0 else 3

active_statuses = {"pending", "launched", "running", "stale", "failed", "paused", "stopped"}
counts = {}
retry_high = 0
retry_high_ids = []

try:
    if os.path.exists(inbox_file):
        loaded = yaml.safe_load(open(inbox_file).read()) or []
        items = loaded if isinstance(loaded, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            st = str(item.get("status", ""))
            if st:
                counts[st] = counts.get(st, 0) + 1
            if st in active_statuses:
                rc = int(item.get("retry_count") or 0)
                if rc >= threshold:
                    retry_high += 1
                    item_id = str(item.get("id", ""))
                    if item_id:
                        retry_high_ids.append(item_id)
except Exception:
    pass

approvals_pending = 0
try:
    if os.path.isdir(handoff_dir):
        for path in sorted(glob_mod.glob(os.path.join(handoff_dir, "*.yaml"))):
            try:
                y = yaml.safe_load(open(path).read()) or {}
                if not isinstance(y, dict):
                    continue
                status = str(y.get("status", ""))
                gate = y.get("approval_gate")
                required = isinstance(gate, dict) and gate.get("required") is True
                approved = isinstance(gate, dict) and gate.get("approved_by_user") is True
                if status == "pending_user_approval" or (required and not approved):
                    approvals_pending += 1
            except Exception:
                continue
except Exception:
    pass

discussion_counts = {}
try:
    if os.path.isdir(discussions_dir):
        for path in sorted(glob_mod.glob(os.path.join(discussions_dir, "*/state.yaml"))):
            try:
                y = yaml.safe_load(open(path).read()) or {}
                if isinstance(y, dict):
                    st = str(y.get("status", ""))
                    if st:
                        discussion_counts[st] = discussion_counts.get(st, 0) + 1
            except Exception:
                continue
except Exception:
    pass

for k in ["pending", "launched", "running", "paused", "done", "failed", "stale", "stopped"]:
    print(f"{k}={counts.get(k, 0)}")
print(f"retry_high={retry_high}")
print(f"retry_high_ids={','.join(retry_high_ids[:5])}")
print(f"approvals_pending={approvals_pending}")
for k, v in discussion_counts.items():
    if k:
        print(f"discussion_{k}={v}")
PY
)"

pending=0; launched=0; running=0; paused=0; done=0; failed=0; stale=0; stopped=0
retry_high=0; retry_high_ids=""
approvals_pending=0
discussion_active=0; discussion_consensus=0; discussion_failed_participant=0
discussion_deadlock=0; discussion_closed=0
while IFS= read -r _line; do
  _key="${_line%%=*}"
  _val="${_line#*=}"
  case "$_key" in
    pending|launched|running|paused|done|failed|stale|stopped|\
    retry_high|retry_high_ids|approvals_pending)
      declare "$_key=$_val" ;;
    discussion_*)
      [[ "$_key" =~ ^discussion_[a-z_]+$ ]] && declare "$_key=$_val" ;;
  esac
done <<< "$stats"

echo "superharness status"
echo "project: $PROJECT_DIR"
echo "watcher: level=$watcher_level $watcher_msg"
echo "heartbeat: $heartbeat_status ($heartbeat_detail)"
echo "inbox: pending=${pending:-0} launched=${launched:-0} running=${running:-0} paused=${paused:-0} done=${done:-0} failed=${failed} stale=${stale} stopped=${stopped:-0}"
echo "retry-alert: threshold=$RETRY_THRESHOLD high=$retry_high ids=${retry_high_ids:-none}"
echo "approvals: pending=$approvals_pending"
echo "discussions: active=$discussion_active consensus=$discussion_consensus failed_participant=$discussion_failed_participant deadlock=$discussion_deadlock closed=$discussion_closed"

issues=0
if [ "$watcher_level" = "bad" ]; then
  issues=$((issues + 1))
fi
if [ "$heartbeat_status" = "stale" ] || [ "$heartbeat_status" = "missing" ]; then
  issues=$((issues + 1))
fi
if [ "${failed:-0}" -gt 0 ] || [ "${stale:-0}" -gt 0 ] || [ "${retry_high:-0}" -gt 0 ]; then
  issues=$((issues + 1))
fi

echo "summary: issues=$issues"
if [ "$CHECK_MODE" -eq 1 ] && [ "$issues" -gt 0 ]; then
  exit 1
fi
