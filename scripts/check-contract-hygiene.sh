#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  check-contract-hygiene.sh --project DIR [--strict]

Options:
  -p, --project DIR   Project directory containing .superharness/
      --strict        Fail when contract decisions/failures are not promoted to decisions.yaml/failures.yaml
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR=""
STRICT=0

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --strict)
      STRICT=1
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

[ -n "$PROJECT_DIR" ] || { echo "--project is required" >&2; exit 2; }
[ -d "$PROJECT_DIR" ] || { echo "Project directory does not exist: $PROJECT_DIR" >&2; exit 1; }
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"

HARNESS_DIR="$PROJECT_DIR/.superharness"
CONTRACT_FILE="$HARNESS_DIR/contract.yaml"
HANDOFF_DIR="$HARNESS_DIR/handoffs"
LEDGER_FILE="$HARNESS_DIR/ledger.md"
DECISIONS_FILE="$HARNESS_DIR/decisions.yaml"
FAILURES_FILE="$HARNESS_DIR/failures.yaml"

for path in "$HARNESS_DIR" "$CONTRACT_FILE" "$HANDOFF_DIR" "$LEDGER_FILE"; do
  if [ ! -e "$path" ]; then
    echo "Missing required path: $path" >&2
    exit 1
  fi
done

if [ ! -f "$DECISIONS_FILE" ] || [ ! -f "$FAILURES_FILE" ]; then
  echo "Missing decisions/failures store under $HARNESS_DIR" >&2
  exit 1
fi

set +e
analysis="$(
  ruby - "$CONTRACT_FILE" "$HANDOFF_DIR" "$LEDGER_FILE" "$DECISIONS_FILE" "$FAILURES_FILE" << 'RUBY' 2>&1
require "yaml"
require "psych"
require "time"
require "date"

contract_file, handoff_dir, ledger_file, decisions_file, failures_file = ARGV

def safe_load_yaml(path, expected_class)
  content = File.read(path)
  data = Psych.safe_load(content, permitted_classes: [Time, Date], aliases: false)
  data = expected_class == Hash ? {} : [] if data.nil?
  raise "#{File.basename(path)} must be a #{expected_class}" unless data.is_a?(expected_class)
  data
end

contract = safe_load_yaml(contract_file, Hash)

tasks = contract["tasks"]
if tasks.nil?
  tasks = []
elsif !tasks.is_a?(Array)
  raise "tasks must be a sequence"
end

done_tasks = tasks.select do |task|
  task.is_a?(Hash) && task["status"].to_s == "done" && !task["id"].to_s.empty?
end

ledger_text = File.exist?(ledger_file) ? File.read(ledger_file) : ""
handoff_files = Dir.glob(File.join(handoff_dir, "*.yaml"))

handoff_map = {}
handoff_files.each do |file|
  begin
    data = safe_load_yaml(file, Hash)
  rescue StandardError
    next
  end
  next unless data.is_a?(Hash)
  task_id = data["task"].to_s
  next if task_id.empty?
  handoff_map[task_id] ||= []
  handoff_map[task_id] << file
end

done_tasks.each do |task|
  id = task["id"].to_s
  puts "TASK:#{id}"
  if (handoff_map[id] || []).empty?
    puts "MISSING_HANDOFF:#{id}"
  end
  escaped = Regexp.escape(id)
  unless ledger_text.match?(/\b#{escaped}\b/)
    puts "MISSING_LEDGER:#{id}"
  end
end

contract_decisions = contract["decisions"]
contract_decision_count = contract_decisions.is_a?(Array) ? contract_decisions.length : 0
contract_failures = contract["failures"]
contract_failure_count = contract_failures.is_a?(Array) ? contract_failures.length : 0

decisions = safe_load_yaml(decisions_file, Hash)
failures = safe_load_yaml(failures_file, Hash)

decision_store = decisions["decisions"]
failure_store = failures["failures"]

decision_store_count = decision_store.is_a?(Array) ? decision_store.length : 0
failure_store_count = failure_store.is_a?(Array) ? failure_store.length : 0

puts "COUNTS:contract_decisions=#{contract_decision_count},store_decisions=#{decision_store_count},contract_failures=#{contract_failure_count},store_failures=#{failure_store_count}"
RUBY
)"
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  echo "$analysis" >&2
  exit 1
fi

failures=0

while IFS= read -r line; do
  case "$line" in
    MISSING_HANDOFF:*)
      task="${line#MISSING_HANDOFF:}"
      echo "Missing handoff file for done task: $task"
      failures=$((failures + 1))
      ;;
    MISSING_LEDGER:*)
      task="${line#MISSING_LEDGER:}"
      echo "Missing ledger mention for done task: $task"
      failures=$((failures + 1))
      ;;
    COUNTS:*)
      counts="${line#COUNTS:}"
      contract_decisions="$(printf '%s' "$counts" | sed -n 's/.*contract_decisions=\([0-9][0-9]*\).*/\1/p')"
      store_decisions="$(printf '%s' "$counts" | sed -n 's/.*store_decisions=\([0-9][0-9]*\).*/\1/p')"
      contract_failures="$(printf '%s' "$counts" | sed -n 's/.*contract_failures=\([0-9][0-9]*\).*/\1/p')"
      store_failures="$(printf '%s' "$counts" | sed -n 's/.*store_failures=\([0-9][0-9]*\).*/\1/p')"
      contract_decisions="${contract_decisions:-0}"
      store_decisions="${store_decisions:-0}"
      contract_failures="${contract_failures:-0}"
      store_failures="${store_failures:-0}"

      if [ "$STRICT" -eq 1 ] && [ "$contract_decisions" -gt 0 ] && [ "$store_decisions" -eq 0 ]; then
        echo "Contract has decisions but decisions.yaml is empty. Promote reusable decisions."
        failures=$((failures + 1))
      fi
      if [ "$STRICT" -eq 1 ] && [ "$contract_failures" -gt 0 ] && [ "$store_failures" -eq 0 ]; then
        echo "Contract has failures but failures.yaml is empty. Promote reusable failures."
        failures=$((failures + 1))
      fi
      ;;
  esac
done << EOF
$analysis
EOF

if [ "$failures" -ne 0 ]; then
  echo ""
  echo "Contract hygiene check failed with $failures issue(s)."
  exit 1
fi

echo "Contract hygiene check passed."
