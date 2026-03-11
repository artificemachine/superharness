#!/usr/bin/env ruby
# frozen_string_literal: true

# Shared YAML loading helpers for all engine scripts.
# Consolidates safe_load patterns from contract.rb, inbox.rb, and validate.rb.

require "psych"
require "time"
require "date"

module YamlHelpers
  PERMITTED_CLASSES = [Time, Date].freeze

  # Load a YAML file safely. Returns the expected type's empty value if file
  # is missing or contains nil. Raises on type mismatch.
  def self.safe_load(path, expected_class)
    return(expected_class == Hash ? {} : []) unless File.exist?(path)
    content = File.read(path)
    data = Psych.safe_load(content, permitted_classes: PERMITTED_CLASSES, aliases: false)
    return(expected_class == Hash ? {} : []) if data.nil?
    raise "YAML document has unexpected type in #{path}" unless data.is_a?(expected_class)
    data
  end

  # Load and normalize Time/Date scalars to ISO 8601 strings.
  def self.safe_load_normalized(path, expected_class)
    data = safe_load(path, expected_class)
    normalize_scalar_values(data)
  end

  def self.normalize_scalar_values(value)
    case value
    when Time then value.utc.iso8601
    when Date then value.iso8601
    when Array then value.map { |v| normalize_scalar_values(v) }
    when Hash then value.transform_values { |v| normalize_scalar_values(v) }
    else value
    end
  end
end
