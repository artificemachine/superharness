#!/usr/bin/env ruby
# frozen_string_literal: true

# Shared file-level locking and atomic write helpers.
# Used by discuss.rb, discussion.rb, and any engine that needs
# concurrent-safe file operations.

require "tempfile"
require_relative "yaml_helpers"

module FileUtils_SH
  # File-level advisory lock with timeout.
  def self.with_file_lock(path, timeout: 5)
    lock_path = "#{path}.flock"
    File.open(lock_path, File::CREAT | File::RDWR) do |lock_file|
      unless lock_file.flock(File::LOCK_EX | File::LOCK_NB)
        deadline = Time.now + timeout
        loop do
          break if lock_file.flock(File::LOCK_EX | File::LOCK_NB)
          if Time.now >= deadline
            abort("E_LOCK_TIMEOUT: could not acquire lock on #{path} within #{timeout}s")
          end
          sleep 0.1
        end
      end
      yield
    end
  end

  # Acquire multiple locks in a fixed order (prevents deadlocks).
  def self.with_multi_lock(paths, timeout: 5, &block)
    if paths.empty?
      yield
    else
      with_file_lock(paths.first, timeout: timeout) do
        with_multi_lock(paths[1..], timeout: timeout, &block)
      end
    end
  end

  # Load YAML via YamlHelpers (convenience wrapper).
  def self.load_yaml(path, expected_class)
    YamlHelpers.safe_load(path, expected_class)
  end

  # Atomic write: write to temp file then rename into place.
  def self.atomic_write(path, content)
    dir = File.dirname(path)
    base = File.basename(path)
    tmp = Tempfile.new([base, ".tmp"], dir)
    begin
      tmp.write(content)
      tmp.flush
      tmp.fsync rescue nil
      tmp.close
      File.rename(tmp.path, path)
    ensure
      begin
        tmp.close unless tmp.closed?
      rescue IOError
        nil
      end
      File.unlink(tmp.path) if File.exist?(tmp.path)
    end
  end
end
