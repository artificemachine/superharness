#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  notify.sh [--project DIR] [--retry-threshold N] [--watcher-down-streak N] [--cooldown-minutes N] [--webhook-url URL] [--state-file FILE] [--dry-run]

Options:
  -p, --project DIR        Project directory containing .superharness/ (default: current dir)
      --retry-threshold N  Trigger alert when retry_count >= N (default: 3)
      --watcher-down-streak N  Trigger watcher-down alert after N consecutive runs (default: 3)
      --cooldown-minutes N Alert cooldown for identical fingerprint (default: 30)
      --webhook-url URL    Optional webhook endpoint for JSON POST alerts
      --state-file FILE    Persistent state file (default: .superharness/notify.state)
      --dry-run            Evaluate and print; do not send external notifications
  -h, --help               Show this help message and exit

Exit codes:
  0   no alert condition
  10  alert triggered and delivered (or printed in dry-run)
  11  alert condition present but suppressed by cooldown/fingerprint
USAGE
}

PROJECT_DIR="$(pwd)"
RETRY_THRESHOLD=3
WATCHER_DOWN_STREAK_THRESHOLD=3
COOLDOWN_MINUTES=30
WEBHOOK_URL=""
STATE_FILE=""
DRY_RUN=0

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
    --watcher-down-streak)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      WATCHER_DOWN_STREAK_THRESHOLD="$2"
      shift 2
      ;;
    --cooldown-minutes)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      COOLDOWN_MINUTES="$2"
      shift 2
      ;;
    --webhook-url)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      WEBHOOK_URL="$2"
      shift 2
      ;;
    --state-file)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      STATE_FILE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
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

for v in "$RETRY_THRESHOLD" "$WATCHER_DOWN_STREAK_THRESHOLD" "$COOLDOWN_MINUTES"; do
  case "$v" in
    ''|*[!0-9]*)
      echo "Numeric options must be non-negative integers" >&2
      exit 2
      ;;
  esac
done
if [ "$RETRY_THRESHOLD" -le 0 ] || [ "$WATCHER_DOWN_STREAK_THRESHOLD" -le 0 ]; then
  echo "--retry-threshold and --watcher-down-streak must be positive integers" >&2
  exit 2
fi

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Project directory does not exist: $PROJECT_DIR" >&2
  exit 1
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
HARNESS_DIR="$PROJECT_DIR/.superharness"
[ -d "$HARNESS_DIR" ] || { echo "Missing .superharness in project: $PROJECT_DIR" >&2; exit 1; }
INBOX_FILE="$HARNESS_DIR/inbox.yaml"
STATE_FILE="${STATE_FILE:-$HARNESS_DIR/notify.state}"

watcher_ok=1
watcher_detail=""
PLATFORM="$(uname -s)"
if [ "$PLATFORM" = "Darwin" ]; then
  slug="$(basename "$PROJECT_DIR" | tr -cs 'A-Za-z0-9' '-')"
  label="com.superharness.inbox.${slug}"
  if launchctl_out="$(launchctl print "gui/$(id -u)/$label" 2>/dev/null)"; then
    state="$(printf '%s\n' "$launchctl_out" | sed -n 's/^[[:space:]]*state = //p' | head -n1)"
    last_exit="$(printf '%s\n' "$launchctl_out" | sed -n 's/^[[:space:]]*last exit code = //p' | head -n1)"
    if [ "$state" = "running" ] || [ "$state" = "active" ] || { [ "$state" = "not running" ] && { [ "$last_exit" = "0" ] || [ "$last_exit" = "(never exited)" ]; }; }; then
      watcher_ok=1
      watcher_detail="state=${state:-unknown} exit=${last_exit:-unknown}"
    else
      watcher_ok=0
      watcher_detail="state=${state:-unknown} exit=${last_exit:-unknown}"
    fi
  else
    watcher_ok=0
    watcher_detail="not loaded"
  fi
fi

stats="$(
  ruby - "$INBOX_FILE" "$RETRY_THRESHOLD" <<'RUBY'
require "yaml"
require "date"
inbox_file, retry_threshold = ARGV
threshold = retry_threshold.to_i
threshold = 3 if threshold <= 0
active_statuses = %w[pending launched running stale failed paused stopped]
retry_high_ids = []
if File.exist?(inbox_file)
  items = YAML.safe_load(File.read(inbox_file), permitted_classes: [Time, Date], aliases: false)
  items = [] unless items.is_a?(Array)
  items.each do |item|
    next unless item.is_a?(Hash)
    next unless active_statuses.include?(item["status"].to_s)
    rc = (item["retry_count"] || 0).to_i
    retry_high_ids << item["id"].to_s if rc >= threshold && !item["id"].to_s.empty?
  end
end
puts "retry_high=#{retry_high_ids.length}"
puts "retry_ids=#{retry_high_ids.first(10).join(",")}"
RUBY
)"
retry_high=0
retry_ids=""
while IFS= read -r _line; do
  _key="${_line%%=*}"
  _val="${_line#*=}"
  case "$_key" in
    retry_high|retry_ids) declare "$_key=$_val" ;;
  esac
done <<< "$stats"

mkdir -p "$(dirname "$STATE_FILE")"
prev_watcher_streak=0
prev_last_sent=0
prev_fingerprint=""
if [ -f "$STATE_FILE" ]; then
  prev_watcher_streak="$(sed -n 's/^WATCHER_DOWN_STREAK=//p' "$STATE_FILE" | head -n1)"
  prev_last_sent="$(sed -n 's/^LAST_SENT_EPOCH=//p' "$STATE_FILE" | head -n1)"
  prev_fingerprint="$(sed -n 's/^LAST_FINGERPRINT=//p' "$STATE_FILE" | head -n1)"
  case "$prev_watcher_streak" in ''|*[!0-9]*) prev_watcher_streak=0 ;; esac
  case "$prev_last_sent" in ''|*[!0-9]*) prev_last_sent=0 ;; esac
fi

watcher_streak="$prev_watcher_streak"
if [ "$watcher_ok" -eq 1 ]; then
  watcher_streak=0
else
  watcher_streak=$((watcher_streak + 1))
fi

alerts=()
if [ "$watcher_ok" -eq 0 ] && [ "$watcher_streak" -ge "$WATCHER_DOWN_STREAK_THRESHOLD" ]; then
  alerts+=("watcher_down:${watcher_streak} (${watcher_detail})")
fi
if [ "$retry_high" -gt 0 ]; then
  alerts+=("retry_threshold:${retry_high} item(s) >= ${RETRY_THRESHOLD} [${retry_ids:-none}]")
fi

now_epoch="$(date +%s)"
cooldown_seconds=$((COOLDOWN_MINUTES * 60))
fingerprint="watcher=${watcher_ok}:${watcher_streak}|retry=${retry_high}:${retry_ids}"

should_send=0
if [ "${#alerts[@]}" -gt 0 ]; then
  if [ "$prev_fingerprint" != "$fingerprint" ]; then
    should_send=1
  elif [ "$((now_epoch - prev_last_sent))" -ge "$cooldown_seconds" ]; then
    should_send=1
  fi
fi

{
  echo "WATCHER_DOWN_STREAK=$watcher_streak"
  echo "LAST_SENT_EPOCH=$prev_last_sent"
  echo "LAST_FINGERPRINT=$prev_fingerprint"
} > "$STATE_FILE"

if [ "${#alerts[@]}" -eq 0 ]; then
  echo "notify: no alerts (watcher_ok=$watcher_ok retry_high=$retry_high)"
  exit 0
fi

message="superharness alert for $PROJECT_DIR: $(IFS='; '; echo "${alerts[*]}")"

if [ "$should_send" -eq 0 ]; then
  echo "notify: alert suppressed by cooldown/fingerprint"
  echo "$message"
  exit 11
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "notify: dry-run"
  echo "$message"
else
  echo "$message"
  if [ -n "$WEBHOOK_URL" ] && command -v curl >/dev/null 2>&1; then
    payload="$(printf '{"project":"%s","timestamp":"%s","alerts":["%s"]}' \
      "$PROJECT_DIR" \
      "$(date -u +%FT%TZ)" \
      "$(printf '%s' "${alerts[*]}" | sed 's/"/\\"/g')")"
    curl -fsS -X POST -H "Content-Type: application/json" -d "$payload" "$WEBHOOK_URL" >/dev/null 2>&1 || true
  fi
  if [ "$PLATFORM" = "Darwin" ] && command -v osascript >/dev/null 2>&1; then
    osascript -e "display notification \"${message//\"/\\\"}\" with title \"superharness\"" >/dev/null 2>&1 || true
  elif [ "$PLATFORM" = "Linux" ] && command -v notify-send >/dev/null 2>&1; then
    notify-send "superharness" "$message" >/dev/null 2>&1 || true
  fi
fi

{
  echo "WATCHER_DOWN_STREAK=$watcher_streak"
  echo "LAST_SENT_EPOCH=$now_epoch"
  echo "LAST_FINGERPRINT=$fingerprint"
} > "$STATE_FILE"

exit 10
