#!/usr/bin/env ruby
# frozen_string_literal: true

script_dir = File.expand_path("..", __dir__)
engine = File.join(script_dir, "engine", "inbox.rb")
abort("Missing engine inbox helper: #{engine}") unless File.file?(engine)

exec("ruby", engine, *ARGV)
