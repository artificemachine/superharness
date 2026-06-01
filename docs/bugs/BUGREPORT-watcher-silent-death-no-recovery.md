# BUGREPORT: Watcher silent death — no auto-recovery (19+ hour outage)

> **Project:** superharness (operator daemon)
> **Discovered:** 2026-06-01, during trayzury session
> **Severity:** HIGH — blocks all automated agent dispatch silently
> **Reproducible:** Yes — any unhandled exception in `monitor_and_recover()` kills the daemon

---

## Summary

The watcher for the trayzury project went stale for **19+ hours** with zero auto-recovery. Discussion tasks enqueued for codex-cli and gemini-cli sat unprocessed. No alert, no log, no restart — the system appeared operational but did nothing.

## Root Causes (4 independent failures)

### 1. No launchd service installed for the project

The operator was started manually via terminal (`shux operator start`). When the daemon process died, nothing existed to restart it.

| What exists | Status |
|---|---|
| `com.superharness.operator.4b318084.plist` (trayzury) | **Did not exist** before manual fix |
| `com.superharness.operator.f37a0c08.plist` (nemorad) | Exists but `KeepAlive=false` |
| `com.superharness.operator-watchdog.plist` (global) | Exists but `KeepAlive=false`, runs from wrong directory |

**Fix:** `shux operator install` creates a `KeepAlive=true` launchd plist, now done for trayzury.

### 2. `monitor_and_recover()` loop has no exception handler

```python
# operator.py ~line 204-228
def monitor_and_recover(self, poll_interval: int = 5):
    while not self._stopping:
        for name, proc in list(self.processes.items()):
            if proc.poll() is not None:
                # restart watcher/dashboard subprocess
                ...
        time.sleep(poll_interval)
```

Only `KeyboardInterrupt` is caught. **Any other exception** (during `proc.poll()`, `_spawn_watcher()`, `time.sleep()`, or an import error from module reload) kills the daemon silently.

**Fix:** Wrap the loop body in `try/except Exception as e: logger.error(...); time.sleep(5); continue`.

### 3. SQLite state database never initialized

```
/Users/airm2max/DevOpsSec/trayzury/.superharness/state.sqlite3: 0 bytes, 0 tables
```

The database that is the **source of truth for heartbeats** was never created. All `write_heartbeat()` calls to SQLite failed silently (caught by bare `except Exception: pass` in `heartbeat_contract.py` line 103). The only surviving heartbeat was a legacy plain-text file at `.superharness/watcher.heartbeat`, which froze at the last successful write before the daemon died.

**Fix:** On operator startup, explicitly verify the SQLite DB is initialized (`CREATE TABLE IF NOT EXISTS`). If the DB is 0 bytes, delete it and re-create. Log any heartbeat write failures instead of silently dropping them.

### 4. Watchdog plist runs from wrong directory

```xml
<!-- com.superharness.operator-watchdog.plist -->
<array>
    <string>python</string>
    <string>-m</string><string>superharness.cli</string>
    <string>operator</string><string>heal</string>
    <string>--quiet</string>
</array>
```

No `--project` flag. No `WorkingDirectory` key. The `heal` command computes `md5(".").hexdigest()[:8]` from launchd's working directory (likely `$HOME`), which never matches any project. The watchdog looks for a plist that will never exist.

Additionally, `KeepAlive=false` means launchd won't retry after the first failure. The watchdog log files are 0 bytes — the command likely failed to even import `superharness.cli`.

**Fix A:** Add `WorkingDirectory` or `--project` discovery to the watchdog plist generator (`launchd_health.py`, `write_watchdog_plist()`).

**Fix B:** Set `KeepAlive=true` on the watchdog plist.

**Fix C:** The `operator heal` command should auto-discover all directories containing `.superharness/` rather than relying on a single `--project` flag.

## Timeline

| Time (UTC+2) | Event |
|---|---|
| ~2026-05-31 20:00 | Operator daemon dies (cause unknown; no logs) |
| ~19 hours | Watcher stale; all enqueued tasks orphaned |
| 2026-06-01 16:13 | Operator manually restarted (`shux operator start`) |
| 2026-06-01 16:22 | `shux operator install` → launchd plist created with KeepAlive |

## Fix Priority

| # | Fix | Effort | Impact |
|---|-----|:---:|---|
| 1 | `operator install` for all projects with `.superharness/` | Manual | Prevents future silent death |
| 2 | `try/except Exception` in `monitor_and_recover()` | S | Prevents silent crash |
| 3 | SQLite init verification on startup | S | Heartbeats actually work |
| 4 | Watchdog `--project` discovery | M | Auto-heal works |

## Related

- `docs/bulletproof-report-2026-05-24-sqlite-sot.md` — prior report about SQLite source-of-truth issues
- `docs/REPORT-process-leak-2026-05-28.md` — prior watcher/process leak report
