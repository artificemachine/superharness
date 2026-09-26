# BUG 2026-09-24: `shux operator stop` refuses to stop an operator started from the shell

- Affected: `shux operator stop` for an operator started with `shux operator start` (not the
  installed launchd service), on 1.86.4 and earlier.
- Severity: medium. The operator cannot be stopped through the CLI, and the stop forgets it, so the
  singleton guard no longer protects against a second operator.
- Evidence level: observed once on 1.86.4 (installed wheel built from `588d67ad`); the cause is
  confirmed by reading the code.

## Observed

In a scratch project (`git init`, `shux init`):

```
$ shux operator start --project . --no-open
monitor pid: 14767
$ shux operator stop --project .
Refusing to signal unverified operator PID 14767.
$ ps -p 14767 -o command=
.../Python <HOME>/.local/bin/shux operator start --project . --no-open
```

The process kept running and had to be stopped with `kill -TERM 14767`.

## Cause

`operator_stop` in `src/superharness/cli.py` (fallback path, lines 1561-1578 on `588d67ad`) only
signals the recorded pid when its command line contains both:

- the literal `superharness.cli operator start` (line 1572), and
- the absolute project path.

That shape matches only `python -m superharness.cli operator start --project <absolute path>`.
The documented way to start an operator is the console script, whose command line is
`.../shux operator start --project .`: it contains neither the module name nor, with a relative
`--project`, the absolute path. The installed launchd service does match the module form
(`install-operator-service.sh`, `ProgramArguments` lines 44-49), but it never reaches this check
because `operator_stop` handles it earlier with `disable` and `bootout`.

Before 1.86.4 the defect was hidden: `operator-state.json` recorded the parent pid, which exits
right after the fork, so `ps` returned an empty command and the refusal looked like stale-state
cleanup. 1.86.4 records the live daemon pid (PR #154), which makes the refusal visible.

## Consequence beyond the refusal

After refusing, `operator_stop` still removes `operator_pid` and `operator_started_at` from
`operator-state.json`. The operator keeps running, untracked, and the next `shux operator start`
passes `_check_singleton` and starts a second operator for the same project.

## Suggested fix

- Verify the process by identity recorded at start, not by the shape of its command line: store
  the daemon pid together with its process start time (or a nonce passed in its environment) and
  compare on stop. A command-line check, if kept, should accept both the console script
  (`shux`/`superharness` followed by `operator start`) and the module form, and compare the
  resolved `--project` against the process working directory.
- On refusal, keep `operator_pid` in the state file and exit non-zero, so the singleton guard
  still sees the live operator and scripts notice the failure.
- Regression tests:
  - `operator stop` signals a pid whose command line is `.../shux operator start --project .`
    when the recorded identity matches;
  - a refused stop leaves `operator_pid` in place;
  - the existing `test_operator_stop_refuses_unverified_fallback_pid`
    (`tests/unit/test_operator_launchd_lifecycle.py:56`) still refuses an unrelated process.
