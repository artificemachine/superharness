#!/usr/bin/env ruby
# frozen_string_literal: true

require "optparse"
require "yaml"
require "psych"
require "time"
require "date"

HEADER = <<~HDR
  # Delegation inbox
  # status: pending|launched|running|done|failed|stale
HDR

ARCHIVE_HEADER = "# Inbox archive\n"

def load_yaml_document(path, expected_class)
  return(expected_class == Hash ? {} : []) unless File.exist?(path)
  content = File.read(path)
  data = Psych.safe_load(content, permitted_classes: [Time, Date], aliases: false)
  return(expected_class == Hash ? {} : []) if data.nil?
  raise "YAML document has unexpected type in #{path}" unless data.is_a?(expected_class)
  normalize_scalar_values(data)
end

def normalize_scalar_values(value)
  case value
  when Time then value.utc.iso8601
  when Date then value.iso8601
  when Array then value.map { |v| normalize_scalar_values(v) }
  when Hash then value.transform_values { |v| normalize_scalar_values(v) }
  else value
  end
end

def load_items(path)
  load_yaml_document(path, Array)
end

def write_items(path, items)
  tmp = "#{path}.tmp.#{$$}"
  File.write(tmp, HEADER + YAML.dump(items))
  File.rename(tmp, path)
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
  puts [
    item["id"].to_s,
    item["to"].to_s,
    item["task"].to_s,
    item["project"].to_s,
    (item["retry_count"] || 0).to_i.to_s,
    (item["max_retries"] || 3).to_i.to_s,
    best[:prio].to_s
  ].join("|")
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
  exit launch(file: opts[:file], id: opts[:id], now: opts[:now])
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
  exit set_status(file: opts[:file], id: opts[:id], from: opts[:from], to: opts[:to], now: opts[:now], stamp_key: opts[:stamp_key])
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
  exit normalize(
    file: opts[:file],
    drop_statuses: opts[:drop_statuses],
    drop_prefixes: opts[:drop_prefixes],
    archive_file: opts[:archive_file],
    now: opts[:now]
  )
else
  abort("Usage: inbox.rb <next_pending|launch|set_status|normalize> [options]")
end
