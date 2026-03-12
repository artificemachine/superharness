#!/usr/bin/env ruby
# frozen_string_literal: true

require "optparse"
require_relative "yaml_helpers"

def safe_load(path, expected)
  YamlHelpers.safe_load(path, expected)
end

def task_exists(file:, task:)
  doc = safe_load(file, Hash)
  tasks = doc["tasks"]
  if tasks.nil?
    puts "false"
    return 0
  end
  raise "contract tasks must be a sequence: #{file}" unless tasks.is_a?(Array)
  puts(tasks.any? { |t| t.is_a?(Hash) && t["id"].to_s == task.to_s } ? "true" : "false")
  0
end

def task_project_path(file:, task:)
  doc = safe_load(file, Hash)
  tasks = doc["tasks"]
  return 0 if tasks.nil?
  raise "contract tasks must be a sequence: #{file}" unless tasks.is_a?(Array)
  row = tasks.find { |t| t.is_a?(Hash) && t["id"].to_s == task.to_s }
  return 0 if row.nil?
  val = row["project_path"]
  warn "contract: task #{task} has no project_path" if val.nil?
  puts val.to_s
  0
end

def task_owner(file:, task:)
  doc = safe_load(file, Hash)
  tasks = doc["tasks"]
  return 0 if tasks.nil?
  raise "contract tasks must be a sequence: #{file}" unless tasks.is_a?(Array)
  row = tasks.find { |t| t.is_a?(Hash) && t["id"].to_s == task.to_s }
  return 0 if row.nil?
  val = row["owner"]
  warn "contract: task #{task} has no owner" if val.nil?
  puts val.to_s
  0
end

def task_status(file:, task:)
  doc = safe_load(file, Hash)
  tasks = doc["tasks"]
  return 0 if tasks.nil?
  raise "contract tasks must be a sequence: #{file}" unless tasks.is_a?(Array)
  row = tasks.find { |t| t.is_a?(Hash) && t["id"].to_s == task.to_s }
  return 0 if row.nil?
  val = row["status"]
  warn "contract: task #{task} has no status" if val.nil?
  puts val.to_s
  0
end

def contract_id(file:)
  doc = safe_load(file, Hash)
  puts(doc["id"].to_s)
  0
end

def task_deadline_minutes(file:, task:)
  doc = safe_load(file, Hash)
  tasks = doc["tasks"]
  return 0 if tasks.nil?
  raise "contract tasks must be a sequence: #{file}" unless tasks.is_a?(Array)
  row = tasks.find { |t| t.is_a?(Hash) && t["id"].to_s == task.to_s }
  return 0 if row.nil?
  val = row["deadline_minutes"]
  puts val.to_s if val
  0
end

def latest_handoff_task(dir:, to:)
  files = Dir.glob(File.join(dir, "*.yaml")).sort_by { |f| File.mtime(f) }.reverse
  files.each do |file|
    begin
      data = safe_load(file, Hash)
    rescue StandardError => e
      abort("Failed to parse handoff #{file}: #{e.message}")
    end
    next unless data["to"].to_s == to.to_s
    task = data["task"].to_s
    next if task.empty?
    puts "#{task}|#{file}"
    return 0
  end
  0
end

cmd = ARGV.shift
case cmd
when "task_exists"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--task TASK_ID") { |v| opts[:task] = v }
  end.parse!(ARGV)
  abort("--file and --task are required") unless opts[:file] && opts[:task]
  exit task_exists(file: opts[:file], task: opts[:task])
when "task_project_path"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--task TASK_ID") { |v| opts[:task] = v }
  end.parse!(ARGV)
  abort("--file and --task are required") unless opts[:file] && opts[:task]
  exit task_project_path(file: opts[:file], task: opts[:task])
when "task_owner"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--task TASK_ID") { |v| opts[:task] = v }
  end.parse!(ARGV)
  abort("--file and --task are required") unless opts[:file] && opts[:task]
  exit task_owner(file: opts[:file], task: opts[:task])
when "task_status"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--task TASK_ID") { |v| opts[:task] = v }
  end.parse!(ARGV)
  abort("--file and --task are required") unless opts[:file] && opts[:task]
  exit task_status(file: opts[:file], task: opts[:task])
when "contract_id"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
  end.parse!(ARGV)
  abort("--file is required") unless opts[:file]
  exit contract_id(file: opts[:file])
when "latest_handoff_task"
  opts = {}
  OptionParser.new do |o|
    o.on("--dir DIR") { |v| opts[:dir] = v }
    o.on("--to TARGET") { |v| opts[:to] = v }
  end.parse!(ARGV)
  abort("--dir and --to are required") unless opts[:dir] && opts[:to]
  exit latest_handoff_task(dir: opts[:dir], to: opts[:to])
when "task_deadline_minutes"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--task TASK_ID") { |v| opts[:task] = v }
  end.parse!(ARGV)
  abort("--file and --task are required") unless opts[:file] && opts[:task]
  exit task_deadline_minutes(file: opts[:file], task: opts[:task])
else
  abort("Usage: contract.rb <task_exists|task_project_path|task_owner|task_status|task_deadline_minutes|contract_id|latest_handoff_task> [options]")
end
