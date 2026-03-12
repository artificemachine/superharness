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
  ruby - "$INBOX_FILE" "$HANDOFF_DIR" "$DISCUSSIONS_DIR" "$RETRY_THRESHOLD" <<'RUBY'
require "yaml"
require "date"
inbox_file, handoff_dir, discussions_dir, retry_threshold = ARGV
threshold = retry_threshold.to_i
threshold = 3 if threshold <= 0

active_statuses = %w[pending launched running stale failed paused stopped]
counts = Hash.new(0)
retry_high = 0
retry_high_ids = []
items = []
if File.exist?(inbox_file)
  loaded = YAML.safe_load(File.read(inbox_file), permitted_classes: [Time, Date], aliases: false)
  items = loaded.is_a?(Array) ? loaded : []
end
items.each do |item|
  next unless item.is_a?(Hash)
  st = item["status"].to_s
  counts[st] += 1 unless st.empty?
  next unless active_statuses.include?(st)
  rc = (item["retry_count"] || 0).to_i
  if rc >= threshold
    retry_high += 1
    retry_high_ids << item["id"].to_s unless item["id"].to_s.empty?
  end
end

approvals_pending = 0
if Dir.exist?(handoff_dir)
  Dir.glob(File.join(handoff_dir, "*.yaml")).sort.each do |path|
    y = YAML.safe_load(File.read(path), permitted_classes: [Time, Date], aliases: false)
    next unless y.is_a?(Hash)
    status = y["status"].to_s
    gate = y["approval_gate"]
    required = gate.is_a?(Hash) && gate["required"] == true
    approved = gate.is_a?(Hash) && gate["approved_by_user"] == true
    approvals_pending += 1 if status == "pending_user_approval" || (required && !approved)
  rescue StandardError
    next
  end
end

discussion_counts = Hash.new(0)
if Dir.exist?(discussions_dir)
  Dir.glob(File.join(discussions_dir, "*/state.yaml")).sort.each do |path|
    y = YAML.safe_load(File.read(path), permitted_classes: [Time, Date], aliases: false)
    next unless y.is_a?(Hash)
    discussion_counts[y["status"].to_s] += 1
  rescue StandardError
    next
  end
end

keys = %w[pending launched running paused done failed stale stopped]
keys.each { |k| puts "#{k}=#{counts[k] || 0}" }
puts "retry_high=#{retry_high}"
puts "retry_high_ids=#{retry_high_ids.first(5).join(",")}"
puts "approvals_pending=#{approvals_pending}"
discussion_counts.each { |k, v| puts "discussion_#{k}=#{v}" unless k.to_s.empty? }
RUBY
)"

eval "$stats"

failed="${failed:-0}"
stale="${stale:-0}"
retry_high="${retry_high:-0}"
approvals_pending="${approvals_pending:-0}"
discussion_active="${discussion_active:-0}"
discussion_consensus="${discussion_consensus:-0}"
discussion_failed_participant="${discussion_failed_participant:-0}"
discussion_deadlock="${discussion_deadlock:-0}"
discussion_closed="${discussion_closed:-0}"

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
