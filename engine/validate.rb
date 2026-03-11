#!/usr/bin/env ruby
# frozen_string_literal: true

require "optparse"
require_relative "yaml_helpers"

def safe_load_yaml(path, expected_class)
  YamlHelpers.safe_load(path, expected_class)
end

opts = { strict: false }
OptionParser.new do |o|
  o.on("--project DIR") { |v| opts[:project] = v }
  o.on("--strict") { opts[:strict] = true }
  o.on("-h", "--help") do
    puts <<~HELP
    Usage:
      hygiene --project DIR [--strict]

    Validates contract protocol hygiene for a superharness project.

    Options:
      -p, --project DIR   Project directory containing .superharness/ (required)
      --strict            Warn on empty decision/failure stores
      -h, --help          Show this help message and exit

    Checks:
      - All required protocol files and directories exist
      - Every done task has a matching handoff YAML
      - Every done task appears in ledger.md
      - (strict) Decisions/failures in contract are promoted to store files
    HELP
    exit 0
  end
end.parse!(ARGV)

abort("--project is required") unless opts[:project]
project = File.realpath(opts[:project])
harness_dir = File.join(project, ".superharness")
contract_file = File.join(harness_dir, "contract.yaml")
handoff_dir = File.join(harness_dir, "handoffs")
ledger_file = File.join(harness_dir, "ledger.md")
decisions_file = File.join(harness_dir, "decisions.yaml")
failures_file = File.join(harness_dir, "failures.yaml")

[harness_dir, contract_file, handoff_dir, ledger_file].each do |path|
  unless File.exist?(path)
    warn "Missing required path: #{path}"
    exit 1
  end
end
unless File.file?(decisions_file) && File.file?(failures_file)
  warn "Missing decisions/failures store under #{harness_dir}"
  exit 1
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
  rescue StandardError => e
    puts "Warning: corrupt handoff file #{file}: #{e.message}"
    issues += 1
    next
  end
  task_id = data["task"].to_s
  next if task_id.empty?
  handoff_map[task_id] ||= []
  handoff_map[task_id] << file
end

issues = 0
done_tasks.each do |task|
  id = task["id"].to_s
  if (handoff_map[id] || []).empty?
    puts "Missing handoff file for done task: #{id}"
    issues += 1
  end
  escaped = Regexp.escape(id)
  unless ledger_text.match?(/\b#{escaped}\b/)
    puts "Missing ledger mention for done task: #{id}"
    issues += 1
  end
end

contract_decision_count = contract["decisions"].is_a?(Array) ? contract["decisions"].length : 0
contract_failure_count = contract["failures"].is_a?(Array) ? contract["failures"].length : 0

decisions = safe_load_yaml(decisions_file, Hash)
failures = safe_load_yaml(failures_file, Hash)
decision_store_count = decisions["decisions"].is_a?(Array) ? decisions["decisions"].length : 0
failure_store_count = failures["failures"].is_a?(Array) ? failures["failures"].length : 0

if opts[:strict] && contract_decision_count > 0 && decision_store_count == 0
  puts "Contract has decisions but decisions.yaml is empty. Promote reusable decisions."
  issues += 1
end
if opts[:strict] && contract_failure_count > 0 && failure_store_count == 0
  puts "Contract has failures but failures.yaml is empty. Promote reusable failures."
  issues += 1
end

if issues.positive?
  puts
  puts "Contract hygiene check failed with #{issues} issue(s)."
  exit 1
end

puts "Contract hygiene check passed."
