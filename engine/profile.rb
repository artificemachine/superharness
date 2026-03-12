#!/usr/bin/env ruby
# frozen_string_literal: true

# profile.rb — Read a field from .superharness/profile.yaml
#
# Usage:
#   ruby engine/profile.rb --project /path/to/project FIELD
#
# Outputs the field value to stdout and exits 0.
# If profile.yaml is missing or the field is absent, outputs the default and exits 0.
#
# Known fields and their defaults:
#   autonomy       → approval-gated
#   primary_agent  → (empty string)
#   team_size      → solo
#
# Unknown fields return an empty string.

require "optparse"
require "date"

FIELD_DEFAULTS = {
  "autonomy"      => "approval-gated",
  "primary_agent" => "",
  "team_size"     => "solo",
}.freeze

project_dir = Dir.pwd
field = nil

OptionParser.new do |opts|
  opts.banner = "Usage: profile.rb [--project DIR] FIELD"
  opts.on("-p", "--project DIR", "Project directory (default: cwd)") { |v| project_dir = v }
  opts.on("-h", "--help", "Show help") { puts opts; exit }
end.parse!

field = ARGV.shift
if field.nil? || field.empty?
  $stderr.puts "Usage: profile.rb [--project DIR] FIELD"
  exit 2
end

project_dir = File.expand_path(project_dir)
profile_path = File.join(project_dir, ".superharness", "profile.yaml")

unless File.exist?(profile_path)
  puts FIELD_DEFAULTS.fetch(field, "")
  exit 0
end

begin
  require "psych"
  doc = Psych.safe_load(File.read(profile_path), permitted_classes: [Date]) || {}
rescue StandardError => e
  $stderr.puts "Warning: could not parse profile.yaml: #{e.message}"
  puts FIELD_DEFAULTS.fetch(field, "")
  exit 0
end

value = doc.is_a?(Hash) ? doc[field] : nil

if value.nil?
  puts FIELD_DEFAULTS.fetch(field, "")
else
  puts value.to_s
end
