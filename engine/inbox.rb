#!/usr/bin/env ruby
# frozen_string_literal: true

require "optparse"
require "yaml"
require "json"
require "tempfile"
require_relative "yaml_helpers"

HEADER = <<~HDR
  # Delegation inbox
  # status: pending|launched|running|done|failed|stale
HDR

ARCHIVE_HEADER = "# Inbox archive\n"

def load_yaml_document(path, expected_class)
  YamlHelpers.safe_load_normalized(path, expected_class)
end

def load_items(path)
  load_yaml_document(path, Array)
end

def write_items(path, items)
  dir = File.dirname(path)
  base = File.basename(path)
  tmp = Tempfile.new([base, ".tmp"], dir)
  begin
    tmp.write(HEADER + YAML.dump(items))
    tmp.flush
    tmp.fsync
    tmp.close
    File.rename(tmp.path, path)
  ensure
    if tmp
      begin
        tmp.close unless tmp.closed?
      rescue IOError
        nil
      end
      File.unlink(tmp.path) if File.exist?(tmp.path)
    end
  end
end

# File-level advisory lock to prevent concurrent read-modify-write races.
# Uses flock on a .lock file adjacent to the inbox file.
def with_inbox_lock(path)
  lock_path = "#{path}.flock"
  File.open(lock_path, File::CREAT | File::RDWR) do |lock_file|
    lock_file.flock(File::LOCK_EX)
    yield
  end
end

def append_archive(path, items, now:)
  return if items.empty?
  File.write(path, ARCHIVE_HEADER) unless File.exist?(path)
  File.open(path, "a") do |f|
    f.write("\n")
    f.write("# normalized_at: #{now}\n")
    f.write(YAML.dump(items))
  end
end

def norm_priority(v)
  p = v.to_i
  return 2 if p < 1 || p > 3
  p
end

def next_pending(file:, target: nil)
  items = load_items(file)
  best = nil
  best_idx = nil
  items.each_with_index do |item, idx|
    next unless item.is_a?(Hash)
    next unless item["status"].to_s == "pending"
    next if target && !target.empty? && item["to"].to_s != target

    prio = norm_priority(item["priority"] || 2)
    if best.nil? || prio < best[:prio] || (prio == best[:prio] && idx < best_idx)
      best = { item: item, prio: prio }
      best_idx = idx
    end
  end
  return if best.nil?

  item = best[:item]
  puts JSON.generate(
    {
      "id" => item["id"].to_s,
      "to" => item["to"].to_s,
      "task" => item["task"].to_s,
      "project" => item["project"].to_s,
      "retry_count" => (item["retry_count"] || 0).to_i,
      "max_retries" => (item["max_retries"] || 3).to_i,
      "priority" => best[:prio]
    }
  )
end

def enqueue(file:, id:, to:, task:, project:, priority:, created_at:, retry_count: 0, max_retries: 3)
  items = load_items(file)
  if items.any? { |x| x.is_a?(Hash) && x["id"].to_s == id.to_s }
    puts "result=duplicate_id id=#{id}"
    return 2
  end

  item = {
    "id" => id.to_s,
    "to" => to.to_s,
    "task" => task.to_s,
    "project" => project.to_s,
    "status" => "pending",
    "priority" => norm_priority(priority),
    "retry_count" => retry_count.to_i,
    "max_retries" => max_retries.to_i,
    "created_at" => created_at.to_s
  }

  items << item
  write_items(file, items)
  puts "result=enqueued id=#{id} priority=#{item["priority"]}"
  0
end

def launch(file:, id:, now:)
  items = load_items(file)
  idx = items.index { |x| x.is_a?(Hash) && x["id"].to_s == id.to_s }
  if idx.nil?
    puts "result=not_found"
    return 2
  end

  item = items[idx]
  unless item["status"].to_s == "pending"
    puts "result=status_mismatch status=#{item["status"]}"
    return 3
  end

  retry_count = (item["retry_count"] || 0).to_i
  max_retries = (item["max_retries"] || 3).to_i
  if retry_count >= max_retries
    item["status"] = "failed"
    item["failed_at"] = now
    items[idx] = item
    write_items(file, items)
    puts "result=retry_exhausted retry_count=#{retry_count} max_retries=#{max_retries}"
    return 4
  end

  item["retry_count"] = retry_count + 1
  item["status"] = "launched"
  item["launched_at"] = now
  items[idx] = item
  write_items(file, items)
  puts "result=launched retry_count=#{item["retry_count"]} max_retries=#{max_retries} priority=#{norm_priority(item["priority"] || 2)}"
  0
end

def set_status(file:, id:, from:, to:, now:, stamp_key: nil)
  items = load_items(file)
  idx = items.index { |x| x.is_a?(Hash) && x["id"].to_s == id.to_s }
  return 2 if idx.nil?
  item = items[idx]
  return 3 unless item["status"].to_s == from.to_s

  item["status"] = to
  item[stamp_key] = now if stamp_key && !stamp_key.empty?
  items[idx] = item
  write_items(file, items)
  0
end

def set_field(file:, id:, key:, value:)
  items = load_items(file)
  idx = items.index { |x| x.is_a?(Hash) && x["id"].to_s == id.to_s }
  return 2 if idx.nil?
  item = items[idx]
  if value.nil? || value.to_s.empty?
    item.delete(key)
  else
    item[key] = value
  end
  items[idx] = item
  write_items(file, items)
  0
end

def normalize(file:, drop_statuses:, drop_prefixes:, archive_file: nil, now: nil)
  items = load_items(file)
  statuses = drop_statuses.map(&:to_s)
  prefixes = drop_prefixes.map(&:to_s)

  filtered = []
  dropped = []
  items.each do |item|
    unless item.is_a?(Hash)
      filtered << item
      next
    end
    id = item["id"].to_s
    status = item["status"].to_s
    drop_by_status = statuses.include?(status)
    drop_by_prefix = prefixes.any? { |p| !p.empty? && id.start_with?(p) }
    if drop_by_status || drop_by_prefix
      dropped << item
    else
      filtered << item
    end
  end
  write_items(file, filtered)
  append_archive(archive_file, dropped, now: now || Time.now.utc.iso8601) if archive_file
  0
end

def recover_launched(file:, now:, timeout_minutes:, action:)
  items = load_items(file)
  now_time = Time.parse(now)
  timeout_seconds = timeout_minutes.to_i * 60
  updated = false
  stale_count = 0
  retried_count = 0
  failed_count = 0

  items.each_with_index do |item, idx|
    next unless item.is_a?(Hash)
    next unless item["status"].to_s == "launched"

    launched_at = item["launched_at"].to_s
    next if launched_at.empty?
    begin
      launched_time = Time.parse(launched_at)
    rescue ArgumentError
      # If timestamp is malformed, mark stale so it can be inspected.
      item["status"] = "stale"
      item["stale_at"] = now
      item["stale_reason"] = "invalid_launched_at"
      items[idx] = item
      stale_count += 1
      updated = true
      next
    end
    next if (now_time - launched_time) < timeout_seconds

    if action == "retry"
      retry_count = (item["retry_count"] || 0).to_i
      max_retries = (item["max_retries"] || 3).to_i
      if retry_count >= max_retries
        item["status"] = "failed"
        item["failed_at"] = now
        item["failed_reason"] = "stale_timeout_exhausted"
        failed_count += 1
      else
        item["status"] = "pending"
        item["stale_at"] = now
        item["stale_reason"] = "stale_timeout_retry"
        retried_count += 1
      end
    else
      item["status"] = "stale"
      item["stale_at"] = now
      item["stale_reason"] = "stale_timeout"
      stale_count += 1
    end
    item.delete("launched_at")
    items[idx] = item
    updated = true
  end

  write_items(file, items) if updated
  puts "result=ok updated=#{updated ? 1 : 0} stale=#{stale_count} retried=#{retried_count} failed=#{failed_count}"
  0
end

def list_launched(file:)
  items = load_items(file)
  result = items.select { |x| x.is_a?(Hash) && x["status"].to_s == "launched" }.map do |item|
    {
      "id"          => item["id"].to_s,
      "to"          => item["to"].to_s,
      "task"        => item["task"].to_s,
      "project"     => item["project"].to_s,
      "launched_at" => item["launched_at"].to_s,
      "priority"    => norm_priority(item["priority"] || 2),
      "retry_count" => (item["retry_count"] || 0).to_i,
      "max_retries" => (item["max_retries"] || 3).to_i
    }
  end
  puts JSON.generate(result)
  0
end

def deadline_fail(file:, id:, now:, reason:)
  items = load_items(file)
  idx = items.index { |x| x.is_a?(Hash) && x["id"].to_s == id.to_s }
  if idx.nil?
    puts "result=not_found"
    return 2
  end
  item = items[idx]
  unless item["status"].to_s == "launched"
    puts "result=status_mismatch status=#{item["status"]}"
    return 3
  end
  item["status"] = "failed"
  item["failed_at"] = now
  item["failed_reason"] = reason.to_s.empty? ? "deadline_exceeded" : reason.to_s
  item.delete("launched_at")
  items[idx] = item
  write_items(file, items)
  puts "result=ok id=#{id} task=#{item["task"]} to=#{item["to"]} project=#{item["project"]}"
  0
end

def sync_task_status(file:, task:, to:, now:)
  items = load_items(file)
  active_statuses = %w[pending launched running]
  updated = 0
  items.each_with_index do |item, idx|
    next unless item.is_a?(Hash)
    next unless item["task"].to_s == task.to_s
    next unless active_statuses.include?(item["status"].to_s)
    item["status"] = to
    stamp = case to
            when "done" then "done_at"
            when "failed" then "failed_at"
            when "stopped" then "stopped_at"
            end
    item[stamp] = now if stamp
    item.delete("launched_at")
    item.delete("running_at")
    item.delete("pid")
    items[idx] = item
    updated += 1
  end
  write_items(file, items) if updated > 0
  puts "result=ok synced=#{updated}"
  0
end

cmd = ARGV.shift
case cmd
when "next_pending"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--to TARGET") { |v| opts[:to] = v }
  end.parse!(ARGV)
  abort("--file is required") unless opts[:file]
  next_pending(file: opts[:file], target: opts[:to])
when "launch"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--id ID") { |v| opts[:id] = v }
    o.on("--now TS") { |v| opts[:now] = v }
  end.parse!(ARGV)
  abort("--file, --id, --now are required") unless opts[:file] && opts[:id] && opts[:now]
  with_inbox_lock(opts[:file]) { exit launch(file: opts[:file], id: opts[:id], now: opts[:now]) }
when "enqueue"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--id ID") { |v| opts[:id] = v }
    o.on("--to TARGET") { |v| opts[:to] = v }
    o.on("--task TASK_ID") { |v| opts[:task] = v }
    o.on("--project DIR") { |v| opts[:project] = v }
    o.on("--priority N") { |v| opts[:priority] = v.to_i }
    o.on("--created-at TS") { |v| opts[:created_at] = v }
    o.on("--retry-count N") { |v| opts[:retry_count] = v.to_i }
    o.on("--max-retries N") { |v| opts[:max_retries] = v.to_i }
  end.parse!(ARGV)
  required = %i[file id to task project priority created_at]
  abort("--file, --id, --to, --task, --project, --priority, --created-at are required") unless required.all? { |k| opts.key?(k) }
  with_inbox_lock(opts[:file]) do
    exit enqueue(
      file: opts[:file],
      id: opts[:id],
      to: opts[:to],
      task: opts[:task],
      project: opts[:project],
      priority: opts[:priority],
      created_at: opts[:created_at],
      retry_count: opts.fetch(:retry_count, 0),
      max_retries: opts.fetch(:max_retries, 3)
    )
  end
when "set_status"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--id ID") { |v| opts[:id] = v }
    o.on("--from STATUS") { |v| opts[:from] = v }
    o.on("--to STATUS") { |v| opts[:to] = v }
    o.on("--now TS") { |v| opts[:now] = v }
    o.on("--stamp-key KEY") { |v| opts[:stamp_key] = v }
  end.parse!(ARGV)
  abort("--file, --id, --from, --to, --now are required") unless opts[:file] && opts[:id] && opts[:from] && opts[:to] && opts[:now]
  with_inbox_lock(opts[:file]) { exit set_status(file: opts[:file], id: opts[:id], from: opts[:from], to: opts[:to], now: opts[:now], stamp_key: opts[:stamp_key]) }
when "set_field"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--id ID") { |v| opts[:id] = v }
    o.on("--key KEY") { |v| opts[:key] = v }
    o.on("--value VALUE") { |v| opts[:value] = v }
  end.parse!(ARGV)
  abort("--file, --id, --key are required") unless opts[:file] && opts[:id] && opts[:key]
  with_inbox_lock(opts[:file]) { exit set_field(file: opts[:file], id: opts[:id], key: opts[:key], value: opts[:value]) }
when "normalize"
  opts = { drop_statuses: [], drop_prefixes: [] }
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--drop-status STATUS") { |v| opts[:drop_statuses] << v }
    o.on("--drop-prefix PREFIX") { |v| opts[:drop_prefixes] << v }
    o.on("--archive-file FILE") { |v| opts[:archive_file] = v }
    o.on("--now TS") { |v| opts[:now] = v }
  end.parse!(ARGV)
  abort("--file is required") unless opts[:file]
  opts[:drop_statuses] = ["stale"] if opts[:drop_statuses].empty?
  with_inbox_lock(opts[:file]) do
    exit normalize(
      file: opts[:file],
      drop_statuses: opts[:drop_statuses],
      drop_prefixes: opts[:drop_prefixes],
      archive_file: opts[:archive_file],
      now: opts[:now]
    )
  end
when "recover_launched"
  opts = { timeout_minutes: 20, action: "stale" }
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--now TS") { |v| opts[:now] = v }
    o.on("--timeout-minutes N") { |v| opts[:timeout_minutes] = v.to_i }
    o.on("--action MODE") { |v| opts[:action] = v }
  end.parse!(ARGV)
  abort("--file and --now are required") unless opts[:file] && opts[:now]
  abort("--action must be stale or retry") unless %w[stale retry].include?(opts[:action])
  with_inbox_lock(opts[:file]) do
    exit recover_launched(
      file: opts[:file],
      now: opts[:now],
      timeout_minutes: opts[:timeout_minutes],
      action: opts[:action]
    )
  end
when "list_launched"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
  end.parse!(ARGV)
  abort("--file is required") unless opts[:file]
  exit list_launched(file: opts[:file])
when "deadline_fail"
  opts = { reason: "deadline_exceeded" }
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--id ID") { |v| opts[:id] = v }
    o.on("--now TS") { |v| opts[:now] = v }
    o.on("--reason REASON") { |v| opts[:reason] = v }
  end.parse!(ARGV)
  abort("--file, --id, --now are required") unless opts[:file] && opts[:id] && opts[:now]
  with_inbox_lock(opts[:file]) { exit deadline_fail(file: opts[:file], id: opts[:id], now: opts[:now], reason: opts[:reason]) }
when "sync_task_status"
  opts = {}
  OptionParser.new do |o|
    o.on("--file FILE") { |v| opts[:file] = v }
    o.on("--task TASK_ID") { |v| opts[:task] = v }
    o.on("--to STATUS") { |v| opts[:to] = v }
    o.on("--now TS") { |v| opts[:now] = v }
  end.parse!(ARGV)
  abort("--file, --task, --to, --now are required") unless opts[:file] && opts[:task] && opts[:to] && opts[:now]
  with_inbox_lock(opts[:file]) { exit sync_task_status(file: opts[:file], task: opts[:task], to: opts[:to], now: opts[:now]) }
else
  abort("Usage: inbox.rb <next_pending|launch|enqueue|set_status|sync_task_status|normalize|recover_launched|list_launched|deadline_fail> [options]")
end
