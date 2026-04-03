Task: Verify project-aware monitor detection (v1.3.2) (verify.monitor-project-aware)

## Acceptance Criteria
- shux monitor starts correctly and shux monitor-list shows Project column with project basename
- Starting a second monitor for the same project prints "monitor already running for project X" and exits (no new process)
- Starting a monitor for a different project succeeds and monitor-list shows two separate entries
- shux monitor-kill --project <dir> kills only the monitor for that project
- _is_monitor_running(project_dir) returns (True, port) for running project, (False, None) for unknown project

## Process
1. Read the task details and plan section above
2. Propose a TDD plan (RED → GREEN → REFACTOR) and wait for user confirmation
3. Implement only after user approves the plan
4. Run tests after each phase — all tests must pass before marking done