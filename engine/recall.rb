#!/usr/bin/env ruby
# frozen_string_literal: true

# recall.rb — Search .superharness/handoffs/ and ledger.md by keyword.
#
# Usage:
#   ruby engine/recall.rb --project DIR "term" ["term2" ...]
#   ruby engine/recall.rb --project . --since 7d "deploy"
#
# Multi-keyword logic: OR — any term matching in a file produces a result.

require "optparse"
require "yaml"
require "date"

project_dir = Dir.pwd
since_days  = nil

OptionParser.new do |opts|
  opts.banner = "Usage: recall.rb [--project DIR] [--since Nd] TERM [TERM...]"
  opts.on("-p", "--project DIR", "Project directory (default: cwd)") { |v| project_dir = v }
  opts.on("--since PERIOD", /^\d+d$/, "Limit to last N days (e.g. 7d)") { |v| since_days = v.to_i }
  opts.on("-h", "--help", "Show help") { puts opts; exit 0 }
end.parse!

terms = ARGV.map(&:downcase)
abort "Error: at least one search term required" if terms.empty?

project_dir = File.expand_path(project_dir)
sh_dir = File.join(project_dir, ".superharness")
abort "Not a superharness project (no .superharness/): #{project_dir}" unless File.directory?(sh_dir)

since_date = since_days ? Date.today - since_days : nil

def try_date(str)
  Date.parse(str.to_s) rescue nil
end

def file_date(path, data)
  if data.is_a?(Hash)
    %w[date created completed_at].each do |k|
      d = try_date(data[k]) if data[k]
      return d if d
    end
  end
  m = File.basename(path).match(/^(\d{4}-\d{2}-\d{2})/)
  m ? try_date(m[1]) : nil
end

def file_meta(path, data)
  agent   = (data.is_a?(Hash) && (data["agent"] || data["completed_by"] || data["owner"])) || "unknown"
  task_id = (data.is_a?(Hash) && (data["task_id"] || data["task"] || data["id"])) ||
            File.basename(path, File.extname(path)).sub(/^\d{4}-\d{2}-\d{2}-/, "")
  [agent, task_id]
end

def ctx(lines, idx)
  s = [idx - 1, 0].max
  e = [idx + 1, lines.length - 1].min
  lines[s..e].map(&:strip).reject(&:empty?).first(3).join(" / ")
end

results = []

# --- Scan handoff files ---
handoffs_dir = File.join(sh_dir, "handoffs")
if File.directory?(handoffs_dir)
  Dir.glob(File.join(handoffs_dir, "*.{yaml,yml,md}")).sort.each do |path|
    raw = File.read(path) rescue next
    data = (path.match?(/\.ya?ml$/) ? YAML.safe_load(raw, permitted_classes: [Date]) : nil) rescue nil
    fdate = file_date(path, data)
    next if since_date && fdate && fdate < since_date
    agent, task_id = file_meta(path, data)
    lines = raw.lines.map(&:chomp)
    snippets = []
    count = 0
    terms.each do |term|
      lines.each_with_index do |line, i|
        next unless line.downcase.include?(term)
        count += 1
        s = ctx(lines, i)
        snippets << s unless s.empty? || snippets.include?(s)
      end
    end
    next if count.zero?
    results << { date: fdate, agent: agent, task_id: task_id, count: count, snippets: snippets.first(3) }
  end
end

# --- Scan ledger.md ---
ledger = File.join(sh_dir, "ledger.md")
if File.exist?(ledger)
  File.readlines(ledger).each do |line|
    line = line.chomp
    next if line.strip.empty? || line.start_with?("#")
    ldate = (m = line.match(/(\d{4}-\d{2}-\d{2})/)) ? try_date(m[1]) : nil
    next if since_date && ldate && ldate < since_date
    agent = (m2 = line.match(/— ([\w\-]+) —/)) ? m2[1] : "unknown"
    count = terms.sum { |t| line.downcase.include?(t) ? 1 : 0 }
    next if count.zero?
    results << { date: ldate, agent: agent, task_id: "ledger", count: count, snippets: [line.strip[0, 120]] }
  end
end

# --- Output ---
if results.empty?
  puts "(no results for: #{terms.map { |t| "\"#{t}\"" }.join(", ")})"
  exit 0
end

results.sort_by! { |r| [r[:date] ? -r[:date].jd : Float::INFINITY, -r[:count]] }

results.each do |r|
  puts "#{r[:date] ? r[:date].strftime("%Y-%m-%d") : "unknown"}  #{r[:agent]}  #{r[:task_id]}"
  r[:snippets].each { |s| puts "  \"#{s}\"" }
  puts
end
