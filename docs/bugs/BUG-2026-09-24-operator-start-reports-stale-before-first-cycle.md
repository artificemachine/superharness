# BUG 2026-09-24 — `shux status` right after `shux operator start` reports the fresh watcher as dead, and the printed monitor pid names a process that has already exited

**Severity:** low. Nothing is lost and the watcher works. The cost is a false alarm: an operator (or an agent) who checks status right after starting the stack is told to run the command they just ran, and can reasonably conclude that start failed.
**Status:** open. Observed once on 2026-09-24, macOS, `superharness` at `7e84b592`. Not yet reproduced a second time.

## Summary

Two small defects on the same path:

1. **Stale verdict inside the first watcher cycle.** `shux operator start --port 8787` returned
   at once. `shux status`, run about 3 s later, still reported the previous session's state:

   ```
   watcher: level=bad not loaded, heartbeat stale (last heartbeat 3304m ago)
   heartbeat: stale (last heartbeat 3304m ago)
   ...
     2. heartbeat stale: last heartbeat 3304m ago
   Fix it:
     1. shux operator start
   ```

   About 5 minutes later the same command reported
   `watcher: level=ok foreground (last heartbeat 6s ago)`. The status logic cannot tell a watcher
   that has not finished its first cycle yet (the cycle is 15 s, per `cli.py:1184`) from one that is
   not running. It prescribes `shux operator start` (`commands/status.py:694`), which is the command
   that was just run.

2. **The printed `monitor pid` is the parent, which exits on daemonize.** `cli.py:1181` prints
   `os.getpid()` before the fork at the `# Daemonize: fork+detach` block, so the output was:

   ```
   monitor pid: 81142
     (watcher cycles every 15s)
     daemon pid: 81189
   ```

   Five minutes later `ps -p 81142,81189` listed only `81189`. The pid labelled "monitor" is not a
   process anyone can inspect or kill.

## Reproduction

```bash
cd <any project with a stale heartbeat>
shux operator start --port 8787 && sleep 3 && shux status | head -4   # expected: bad / stale
sleep 20 && shux status | head -4                                     # expected: ok
ps -p <printed monitor pid>,<printed daemon pid> -o pid,command       # only the daemon remains
```

## Suggested fix

- On start, write a "starting" marker (or a heartbeat with `level=starting` and a timestamp) before
  returning. `shux status` then reports `starting (first cycle due in <n>s)` instead of `stale`
  while the marker is younger than one cycle, and prescribes a wait instead of a restart.
- Print the monitor pid from the child after the fork, or print only the daemon pid.
- Regression tests: status within one cycle of start is not `bad`, and the printed pid is alive
  after `operator start` returns.
