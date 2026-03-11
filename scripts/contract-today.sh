#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  contract-today.sh [--project DIR] [--agent claude-code|codex-cli]

Options:
  -p, --project DIR   Project directory containing .superharness/ (default: current dir)
      --agent AGENT   Current agent identity for delegate suggestion context
  -h, --help          Show this help message and exit
USAGE
}

PROJECT_DIR="$(pwd)"
AGENT=""

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --agent)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      AGENT="$2"
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

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Project directory does not exist: $PROJECT_DIR" >&2
  exit 1
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
CONTRACT_FILE="$PROJECT_DIR/.superharness/contract.yaml"

if [ ! -f "$CONTRACT_FILE" ]; then
  echo "Missing contract file: $CONTRACT_FILE" >&2
  exit 1
fi

ruby - "$CONTRACT_FILE" "$AGENT" <<'RUBY'
require "psych"
require "time"
require "date"

contract_file, agent = ARGV

def status_label(s)
  case s.to_s
  when "done" then "✅ done"
  when "in_progress" then "🟡 in_progress"
  when "todo" then "🔲 todo"
  when "failed" then "❌ failed"
  when "stale" then "⚠️ stale"
  else s.to_s.empty? ? "🔲 todo" : s.to_s
  end
end

def pad(str, width)
  str = str.to_s
  str + (" " * [width - str.length, 0].max)
end

def hline(left, mid, right, widths)
  left + widths.map { |w| "─" * (w + 2) }.join(mid) + right
end

def row(cells, widths)
  "│ " + cells.each_with_index.map { |c, i| pad(c, widths[i]) }.join(" │ ") + " │"
end

content = File.read(contract_file)
doc = Psych.safe_load(content, permitted_classes: [Time, Date], aliases: false) || {}

tasks = doc["tasks"].is_a?(Array) ? doc["tasks"] : []
rows_raw = tasks.map do |t|
  [
    t.is_a?(Hash) ? t["id"].to_s : "",
    t.is_a?(Hash) ? t["title"].to_s : "",
    status_label(t.is_a?(Hash) ? t["status"].to_s : ""),
    t.is_a?(Hash) ? t["owner"].to_s : ""
  ]
end

headers = ["ID", "Title", "Status", "Owner"]
widths = headers.each_with_index.map do |h, i|
  [h.length, rows_raw.map { |r| r[i].length }.max || 0].max
end

puts "Contract #{doc["id"] || "unknown"} — #{doc["created"] || "unknown"}"
goal = doc["goal"].to_s
puts "Goal: #{goal}" unless goal.empty?
puts hline("┌", "┬", "┐", widths)
puts row(headers, widths)
puts hline("├", "┼", "┤", widths)
rows_raw.each_with_index do |r, idx|
  puts row(r, widths)
  puts hline("├", "┼", "┤", widths) if idx < rows_raw.length - 1
end
puts hline("└", "┴", "┘", widths)

handoff_dir = File.join(File.dirname(contract_file), "handoffs")
pending_approvals = []
if Dir.exist?(handoff_dir)
  Dir.glob(File.join(handoff_dir, "*.yaml")).sort.each do |file|
    begin
      hdoc = Psych.safe_load(File.read(file), permitted_classes: [Time, Date], aliases: false) || {}
    rescue StandardError
      next
    end
    next unless hdoc.is_a?(Hash)
    gate = hdoc["approval_gate"]
    pending = hdoc["status"].to_s == "pending_user_approval" || (gate.is_a?(Hash) && gate["required"] && !gate["approved_by_user"])
    next unless pending
    pending_approvals << [hdoc["task"].to_s, hdoc["markdown_report"].to_s]
  end
end

if pending_approvals.any?
  puts ""
  puts "⚠️  USER APPROVAL REQUIRED"
  pending_approvals.each do |task_id, report|
    puts "- task=#{task_id} report=#{report}"
    puts "  approve: superharness discuss approve --task #{task_id} --by owner --note \"Approved\""
  end
end

candidate = tasks.find do |t|
  next false unless t.is_a?(Hash)
  status = t["status"].to_s
  owner = t["owner"].to_s
  next false unless ["todo", "in_progress"].include?(status)
  next false if owner.empty?
  agent.empty? || owner != agent
end

if candidate
  puts "I detected owner is #{candidate["owner"]}. Do you want to delegate #{candidate["id"]} now?"
end
RUBY
