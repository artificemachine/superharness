#!/usr/bin/env ruby
# frozen_string_literal: true

require "optparse"
require "psych"
require "time"
require "date"

def safe_load(path, expected)
  return(expected == Hash ? {} : []) unless File.exist?(path)
  content = File.read(path)
  data = Psych.safe_load(content, permitted_classes: [Time, Date], aliases: false)
  return(expected == Hash ? {} : []) if data.nil?
  raise "YAML document has unexpected type in #{path}" unless data.is_a?(expected)
  data
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
  puts row["project_path"].to_s
  0
end

def task_owner(file:, task:)
  doc = safe_load(file, Hash)
  tasks = doc["tasks"]
  return 0 if tasks.nil?
  raise "contract tasks must be a sequence: #{file}" unless tasks.is_a?(Array)
  row = tasks.find { |t| t.is_a?(Hash) && t["id"].to_s == task.to_s }
  return 0 if row.nil?
  puts row["owner"].to_s
  0
end

def task_status(file:, task:)
  doc = safe_load(file, Hash)
  tasks = doc["tasks"]
  return 0 if tasks.nil?
  raise "contract tasks must be a sequence: #{file}" unless tasks.is_a?(Array)
  row = tasks.find { |t| t.is_a?(Hash) && t["id"].to_s == task.to_s }
  return 0 if row.nil?
  puts row["status"].to_s
  0
end

def contract_id(file:)
  doc = safe_load(file, Hash)
  puts(doc["id"].to_s)
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
else
  abort("Usage: contract.rb <task_exists|task_project_path|task_owner|task_status|contract_id|latest_handoff_task> [options]")
end
