# Handoff: verify.monitor-project-aware — DONE

**Task:** Verify project-aware monitor detection (v1.3.2)
**Date:** 2026-03-30
**Agent:** claude-code

## Summary

All 5 acceptance criteria verified. Implementation was already correct in
`src/superharness/cli.py` and `src/superharness/scripts/monitor-ui.py`. 14
unit tests were written and added to `tests/unit/test_cli.py` under a new
`TestMonitorProjectAware` class.

## Acceptance Criteria Status

1. **shux monitor-list shows Project column with project basename** — PASS
   - `cmd_monitor_list` prints `os.path.basename(proj)` in the PROJECT column
   - Tests: `test_monitor_list_shows_project_basename`, `test_monitor_list_shows_pid_port_url_columns`

2. **Starting a second monitor for the same project prints message and exits** — PASS
   - `_run_monitor` calls `_is_monitor_running(proj)` and returns early (no Popen) when already running
   - Prints "monitor ui: http://127.0.0.1:{port}  (already running)" and project path
   - Tests: `test_run_monitor_already_running_shows_url_and_project`, `test_run_monitor_already_running_does_not_start_new_process`

3. **Starting a monitor for a different project succeeds (two separate entries)** — PASS
   - `_is_monitor_running` matches on `os.path.realpath(project_dir)`, so different projects don't block each other
   - Test: `test_is_monitor_running_returns_false_for_unknown_project`, `test_monitor_list_shows_multiple_entries`

4. **shux monitor-kill --project <dir> kills only that project's monitor** — PASS
   - `cmd_monitor_kill` filters `_find_monitor_processes()` by `os.path.realpath(proj)` and sends SIGTERM only to matching PID
   - Tests: `test_monitor_kill_project_kills_matching_process`, `test_monitor_kill_project_not_found_exits_nonzero`

5. **_is_monitor_running(project_dir) returns (True, port) / (False, None)** — PASS
   - Function in `cli.py` lines 141-165 uses `_find_monitor_processes()` + `urlopen` health check
   - Tests: `test_is_monitor_running_returns_true_for_matching_project`, `test_is_monitor_running_returns_false_for_unknown_project`, `test_is_monitor_running_returns_false_when_no_processes`, `test_is_monitor_running_resolves_realpath_for_project`

## Test Results

- 14 new tests in `TestMonitorProjectAware` — all PASS
- 168 total unit tests pass (test_cli.py + test_monitor_ui.py)
- No regressions

## Files Modified

- `tests/unit/test_cli.py` — added `TestMonitorProjectAware` class (14 tests) and imports for `_find_monitor_processes`, `cmd_monitor_kill`, `cmd_monitor_list`
- `.superharness/contract.yaml` — updated summary for `verify.monitor-project-aware`
- `.superharness/ledger.md` — appended verification entry
