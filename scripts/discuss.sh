#!/bin/bash
set -euo pipefail

usage() {
  cat << 'USAGE'
Usage:
  discuss.sh <status|approve> [options]

Status options:
  --project DIR      Project directory containing .superharness/ (default: current dir)
  --task TASK_ID     Optional task id filter

Approve options:
  --project DIR      Project directory containing .superharness/ (default: current dir)
  --task TASK_ID     Required task id to approve
  --by ACTOR         Approver identity (default: owner)
  --note TEXT        Optional approval note

Examples:
  discuss.sh status --project .
  discuss.sh approve --project . --task trial-consensus-approval-gate-20260311 --by owner --note "Approved"
USAGE
}

SUBCMD="${1:-}"
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then
  shift
fi

if [ -z "$SUBCMD" ] || [ "$SUBCMD" = "help" ] || [ "$SUBCMD" = "-h" ] || [ "$SUBCMD" = "--help" ]; then
  usage
  exit 0
fi

PROJECT_DIR="$(pwd)"
TASK_ID=""
ACTOR="owner"
NOTE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --project|-p)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      PROJECT_DIR="$2"
      shift 2
      ;;
    --task)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      TASK_ID="$2"
      shift 2
      ;;
    --by)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      ACTOR="$2"
      shift 2
      ;;
    --note)
      [ $# -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
      NOTE="$2"
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

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd -P)"
HARNESS_DIR="$PROJECT_DIR/.superharness"
HANDOFF_DIR="$HARNESS_DIR/handoffs"
CONTRACT_FILE="$HARNESS_DIR/contract.yaml"
INBOX_FILE="$HARNESS_DIR/inbox.yaml"

[ -d "$HARNESS_DIR" ] || { echo "Missing .superharness directory: $HARNESS_DIR" >&2; exit 1; }
[ -d "$HANDOFF_DIR" ] || { echo "Missing handoffs directory: $HANDOFF_DIR" >&2; exit 1; }

case "$SUBCMD" in
  status)
    ruby - "$HANDOFF_DIR" "$TASK_ID" <<'RUBY'
require "psych"
require "time"
require "date"
require "json"

handoff_dir, task_filter = ARGV

rows = []
Dir.glob(File.join(handoff_dir, "*.yaml")).sort.each do |file|
  begin
    doc = Psych.safe_load(File.read(file), permitted_classes: [Time, Date], aliases: false) || {}
  rescue StandardError
    next
  end
  next unless doc.is_a?(Hash)
  status = doc["status"].to_s
  gate = doc["approval_gate"]
  pending = status == "pending_user_approval" || (gate.is_a?(Hash) && gate["required"] && !gate["approved_by_user"])
  next unless pending
  task = doc["task"].to_s
  next if !task_filter.to_s.empty? && task != task_filter.to_s
  rows << {
    "task" => task,
    "status" => status,
    "required" => gate.is_a?(Hash) ? !!gate["required"] : true,
    "approved_by_user" => gate.is_a?(Hash) ? !!gate["approved_by_user"] : false,
    "approved_at" => gate.is_a?(Hash) ? gate["approved_at"] : nil,
    "markdown_report" => doc["markdown_report"].to_s,
    "file" => file
  }
end

if rows.empty?
  puts "No pending user approvals."
  exit 0
end

puts "Pending user approvals:"
rows.each do |r|
  puts "- task=#{r['task']} status=#{r['status']} approved=#{r['approved_by_user']} report=#{r['markdown_report']}"
  puts "  Approve: superharness discuss approve --task #{r['task']} --by owner --note \"Approved\""
end
RUBY
    ;;

  approve)
    [ -n "$TASK_ID" ] || { echo "--task is required for approve" >&2; exit 2; }
    ruby - "$HANDOFF_DIR" "$CONTRACT_FILE" "$INBOX_FILE" "$TASK_ID" "$PROJECT_DIR" "$ACTOR" "$NOTE" <<'RUBY'
require "psych"
require "time"
require "date"

handoff_dir, contract_file, inbox_file, task_id, project_dir, actor, note = ARGV
now = Time.now.utc.iso8601
resumed_count = 0
enqueued_id = nil
task_owner = ""
task_status = ""
task_project = project_dir

handoff_file = nil
handoff_doc = nil
Dir.glob(File.join(handoff_dir, "*.yaml")).sort_by { |f| File.mtime(f) }.reverse.each do |file|
  begin
    doc = Psych.safe_load(File.read(file), permitted_classes: [Time, Date], aliases: false) || {}
  rescue StandardError
    next
  end
  next unless doc.is_a?(Hash)
  next unless doc["task"].to_s == task_id
  gate = doc["approval_gate"]
  pending = doc["status"].to_s == "pending_user_approval" || (gate.is_a?(Hash) && gate["required"] && !gate["approved_by_user"])
  next unless pending
  handoff_file = file
  handoff_doc = doc
  break
end

abort("No pending approval handoff found for task: #{task_id}") if handoff_file.nil? || handoff_doc.nil?

handoff_doc["approval_gate"] ||= {}
handoff_doc["approval_gate"]["required"] = true
handoff_doc["approval_gate"]["approved_by_user"] = true
handoff_doc["approval_gate"]["approved_at"] = now
handoff_doc["approval_gate"]["approved_by"] = actor.to_s
handoff_doc["approval_gate"]["note"] = note.to_s unless note.to_s.strip.empty?
handoff_doc["status"] = "approved"

# Persist handoff
handoff_tmp = "#{handoff_file}.tmp.#{$$}"
File.write(handoff_tmp, Psych.dump(handoff_doc))
File.rename(handoff_tmp, handoff_file)

# Update contract task status from pending_user_approval -> todo
if File.exist?(contract_file)
  contract_doc = Psych.safe_load(File.read(contract_file), permitted_classes: [Time, Date], aliases: false) || {}
  if contract_doc.is_a?(Hash) && contract_doc["tasks"].is_a?(Array)
    contract_doc["tasks"].each do |t|
      next unless t.is_a?(Hash)
      next unless t["id"].to_s == task_id
      task_owner = t["owner"].to_s
      if t["status"].to_s == "pending_user_approval"
        t["status"] = "todo"
      end
      task_status = t["status"].to_s
      task_project = t["project_path"].to_s unless t["project_path"].to_s.empty?
      if !note.to_s.strip.empty?
        t["summary"] = "User approval granted at #{now} by #{actor}: #{note}"
      else
        t["summary"] = "User approval granted at #{now} by #{actor}"
      end
    end
    contract_tmp = "#{contract_file}.tmp.#{$$}"
    File.write(contract_tmp, Psych.dump(contract_doc))
    File.rename(contract_tmp, contract_file)
  end
end

# Resume inbox items paused for user approval
if File.exist?(inbox_file)
  inbox_doc = Psych.safe_load(File.read(inbox_file), permitted_classes: [Time, Date], aliases: false) || []
  if inbox_doc.is_a?(Array)
    changed = false
    inbox_doc.each do |item|
      next unless item.is_a?(Hash)
      next unless item["task"].to_s == task_id
      next unless item["status"].to_s == "paused"
      next unless item["pause_reason"].to_s == "awaiting_user_approval"
      item["status"] = "pending"
      item["resumed_at"] = now
      resumed_count += 1
      changed = true
    end

    if resumed_count.zero? && !task_owner.empty? && %w[todo in_progress].include?(task_status)
      active = inbox_doc.any? do |item|
        next false unless item.is_a?(Hash)
        item["task"].to_s == task_id && item["to"].to_s == task_owner && %w[pending paused launched running].include?(item["status"].to_s)
      end
      unless active
        enqueued_id = "#{Time.now.utc.strftime('%Y%m%dT%H%M%SZ')}-#{task_id}-#{$$}-#{rand(1_000_000_000)}"
        inbox_doc << {
          "id" => enqueued_id,
          "to" => task_owner,
          "task" => task_id,
          "project" => task_project,
          "status" => "pending",
          "priority" => 1,
          "retry_count" => 0,
          "max_retries" => 3,
          "created_at" => now
        }
        changed = true
      end
    end

    if changed
      inbox_tmp = "#{inbox_file}.tmp.#{$$}"
      File.write(inbox_tmp, Psych.dump(inbox_doc))
      File.rename(inbox_tmp, inbox_file)
    end
  end
elsif !task_owner.empty? && %w[todo in_progress].include?(task_status)
  enqueued_id = "#{Time.now.utc.strftime('%Y%m%dT%H%M%SZ')}-#{task_id}-#{$$}-#{rand(1_000_000_000)}"
  inbox_doc = [
    {
      "id" => enqueued_id,
      "to" => task_owner,
      "task" => task_id,
      "project" => task_project,
      "status" => "pending",
      "priority" => 1,
      "retry_count" => 0,
      "max_retries" => 3,
      "created_at" => now
    }
  ]
  inbox_tmp = "#{inbox_file}.tmp.#{$$}"
  File.write(inbox_tmp, Psych.dump(inbox_doc))
  File.rename(inbox_tmp, inbox_file)
end

puts "Approved consensus for task '#{task_id}' by #{actor}."
puts "Updated handoff: #{handoff_file}"
if resumed_count > 0
  puts "Resumed #{resumed_count} paused inbox item(s) awaiting approval."
elsif enqueued_id
  puts "Auto-enqueued inbox item: #{enqueued_id} (to=#{task_owner}, task=#{task_id}, priority=1)"
else
  puts "No inbox action needed."
end
RUBY
    ;;

  *)
    echo "Unknown discuss subcommand: $SUBCMD" >&2
    usage >&2
    exit 2
    ;;
esac
