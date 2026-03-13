#!/usr/bin/env ruby
# frozen_string_literal: true

# Engine for discuss (approval gate) operations.
# Follows the same patterns as inbox.rb: flock locking, Tempfile+rename,
# yaml_helpers for safe YAML loading.

require "optparse"
require "yaml"
require "json"
require "time"
require_relative "file_utils"

# Convenience delegates to shared FileUtils_SH module.
# Lock order for discuss: 1. handoff file  2. contract.yaml  3. inbox.yaml
def with_file_lock(path, timeout: 5, &block)
  FileUtils_SH.with_file_lock(path, timeout: timeout, &block)
end

def with_multi_lock(paths, timeout: 5, &block)
  FileUtils_SH.with_multi_lock(paths, timeout: timeout, &block)
end

def load_yaml(path, expected_class)
  FileUtils_SH.load_yaml(path, expected_class)
end

def atomic_write(path, content)
  FileUtils_SH.atomic_write(path, content)
end

def find_pending_handoff(handoff_dir, task_id)
  candidates = Dir.glob(File.join(handoff_dir, "*.yaml")).sort
  candidates.each do |file|
    doc = load_yaml(file, Hash)
    next if doc.empty?
    next unless doc["task"].to_s == task_id
    gate = doc["approval_gate"]
    pending = doc["status"].to_s == "pending_user_approval" ||
              (gate.is_a?(Hash) && gate["required"] && !gate["approved_by_user"])
    next unless pending
    return [file, doc]
  end
  nil
end

# --- Commands ---

def cmd_status(handoff_dir:, task_filter:)
  rows = []
  Dir.glob(File.join(handoff_dir, "*.yaml")).sort.each do |file|
    doc = load_yaml(file, Hash)
    next if doc.empty?
    status = doc["status"].to_s
    gate = doc["approval_gate"]
    pending = status == "pending_user_approval" ||
              (gate.is_a?(Hash) && gate["required"] && !gate["approved_by_user"])
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
    return 0
  end

  puts "Pending user approvals:"
  rows.each do |r|
    puts "- task=#{r['task']} status=#{r['status']} approved=#{r['approved_by_user']} report=#{r['markdown_report']}"
    puts "  Approve: superharness discuss approve --task #{r['task']} --by owner --note \"Approved\""
  end
  0
end

def cmd_approve(handoff_dir:, contract_file:, inbox_file:, task_id:, project_dir:, actor:, note:)
  now = Time.now.utc.iso8601
  resumed_count = 0
  enqueued_id = nil
  task_owner = ""
  task_status = ""
  task_project = project_dir

  # Find the pending handoff
  result = find_pending_handoff(handoff_dir, task_id)
  if result.nil?
    $stderr.puts "No pending approval handoff found for task: #{task_id}"
    return 1
  end
  handoff_file, handoff_doc = result

  # Validate state transition: only pending_user_approval can be approved
  current_status = handoff_doc["status"].to_s
  gate = handoff_doc["approval_gate"]
  is_pending = current_status == "pending_user_approval" ||
               (gate.is_a?(Hash) && gate["required"] && !gate["approved_by_user"])
  unless is_pending
    $stderr.puts "Invalid state transition: handoff status '#{current_status}' cannot be approved"
    return 1
  end

  # Lock order: handoff → contract → inbox
  lock_files = [handoff_file]
  lock_files << contract_file if File.exist?(contract_file)
  lock_files << inbox_file

  with_multi_lock(lock_files) do
    # Re-read files under lock to avoid stale reads
    handoff_doc = load_yaml(handoff_file, Hash)
    if handoff_doc.empty? || handoff_doc["task"].to_s != task_id
      $stderr.puts "Handoff file changed during lock acquisition"
      return 1
    end

    # Update handoff
    handoff_doc["approval_gate"] ||= {}
    handoff_doc["approval_gate"]["required"] = true
    handoff_doc["approval_gate"]["approved_by_user"] = true
    handoff_doc["approval_gate"]["approved_at"] = now
    handoff_doc["approval_gate"]["approved_by"] = actor.to_s
    handoff_doc["approval_gate"]["note"] = note.to_s unless note.to_s.strip.empty?
    handoff_doc["status"] = "approved"
    atomic_write(handoff_file, YAML.dump(handoff_doc))

    # Update contract task status
    if File.exist?(contract_file)
      contract_doc = load_yaml(contract_file, Hash)
      if contract_doc.is_a?(Hash) && contract_doc["tasks"].is_a?(Array)
        contract_doc["tasks"].each do |t|
          next unless t.is_a?(Hash)
          next unless t["id"].to_s == task_id
          task_owner = t["owner"].to_s
          # Only transition pending_user_approval -> todo
          if t["status"].to_s == "pending_user_approval"
            t["status"] = "todo"
          elsif %w[done failed closed].include?(t["status"].to_s)
            $stderr.puts "Warning: task '#{task_id}' has status '#{t["status"]}' — approval recorded but status not changed"
          end
          task_status = t["status"].to_s
          task_project = t["project_path"].to_s unless t["project_path"].to_s.empty?
          if !note.to_s.strip.empty?
            t["summary"] = "User approval granted at #{now} by #{actor}: #{note}"
          else
            t["summary"] = "User approval granted at #{now} by #{actor}"
          end
        end
        atomic_write(contract_file, YAML.dump(contract_doc))
      end
    end

    # Resume paused inbox items or auto-enqueue
    if File.exist?(inbox_file)
      inbox_doc = load_yaml(inbox_file, Array)
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
          item["task"].to_s == task_id &&
            item["to"].to_s == task_owner &&
            %w[pending paused launched running].include?(item["status"].to_s)
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

      atomic_write(inbox_file, YAML.dump(inbox_doc)) if changed
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
      atomic_write(inbox_file, YAML.dump(inbox_doc))
    end
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
  0
end

# --- CLI ---

cmd = ARGV.shift
case cmd
when "status"
  opts = {}
  OptionParser.new do |o|
    o.on("--handoff-dir DIR") { |v| opts[:handoff_dir] = v }
    o.on("--task TASK_ID") { |v| opts[:task] = v }
  end.parse!(ARGV)
  abort("--handoff-dir is required") unless opts[:handoff_dir]
  exit cmd_status(handoff_dir: opts[:handoff_dir], task_filter: opts[:task])

when "approve"
  opts = { actor: "owner", note: "" }
  OptionParser.new do |o|
    o.on("--handoff-dir DIR") { |v| opts[:handoff_dir] = v }
    o.on("--contract-file FILE") { |v| opts[:contract_file] = v }
    o.on("--inbox-file FILE") { |v| opts[:inbox_file] = v }
    o.on("--task TASK_ID") { |v| opts[:task] = v }
    o.on("--project-dir DIR") { |v| opts[:project_dir] = v }
    o.on("--by ACTOR") { |v| opts[:actor] = v }
    o.on("--note TEXT") { |v| opts[:note] = v }
  end.parse!(ARGV)
  required = %i[handoff_dir contract_file inbox_file task project_dir]
  missing = required.select { |k| opts[k].nil? || opts[k].to_s.empty? }
  abort("Missing required flags: #{missing.map { |k| "--#{k.to_s.tr('_', '-')}" }.join(', ')}") unless missing.empty?
  exit cmd_approve(
    handoff_dir: opts[:handoff_dir],
    contract_file: opts[:contract_file],
    inbox_file: opts[:inbox_file],
    task_id: opts[:task],
    project_dir: opts[:project_dir],
    actor: opts[:actor],
    note: opts[:note]
  )

else
  abort("Usage: discuss.rb <status|approve> [options]")
end
