# Session Handoff — 2026-04-16

**From:** claude-code
**To:** owner / next session
**Branch:** main (merged from fix/windows-unit-test-hang)
**Version:** 1.24.3 (shipped to PyPI, installed via pipx)

---

## What Was Done

### Fix: Windows CI hang + pre-existing Windows test failures (PR #103)

The Windows unit test suite was hanging at ~69-73% (after ~1063 passes) with a
`KeyboardInterrupt` at `threading.py:327`. Root cause: `os.kill(pid, 0)` on Windows
maps to `GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid)`, which sends Ctrl+C to the
entire console process group — not a safe liveness probe.

#### Root cause fixes (os.kill sweep)

| File | Function | Fix |
|------|----------|-----|
| `inbox_dispatch.py` | `_MkdirLock._pid_alive()` | ctypes `OpenProcess`/`GetExitCodeProcess` Windows path |
| `inbox_watch.py` | `_pid_is_running()` (named fn) | same ctypes pattern |
| `inbox_watch.py` | zombie reconcile inline | replaced `os.kill` try/except with `_pid_is_running()` call |
| `daemon.py` | `_is_pid_alive()` | same ctypes pattern |

The safe Windows pattern (already present in `inbox.py::_process_alive`, used as model):
```python
if sys.platform == "win32":
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong(STILL_ACTIVE)
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        return exit_code.value == STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
```

#### Additional production fix: `launch_agent` Windows .cmd resolution

`platform_runtime.launch_agent` now resolves `.cmd`/`.bat` wrappers via `shutil.which`
and prepends `cmd /c` before calling `subprocess.run`. Without this, agents installed
via npm/pip on Windows (which create `.cmd` wrappers) would fail with WinError 2.

#### 9 pre-existing Windows test failures fixed

| Test | Root cause | Fix |
|------|-----------|-----|
| `test_profile_wiring.py` (4) | `_fake_bin` wrote bash scripts (not Win32 executables); `stdin=DEVNULL` makes NUL report `isatty()=True` on Windows | Created `.cmd` files on Windows; changed to `input=""` (pipe, always non-TTY) |
| `test_project_default_and_path.py` | `/usr/bin:/bin` treated as one path entry on Windows | Use `tmp_path` as initial PATH on Windows |
| `test_recall.py` | `superharness` shim is a bash script, not Win32 executable | Use `sys.executable -m superharness` on Windows |
| `test_status.py` — executable bit | NTFS has no Unix execute bits | `@pytest.mark.skipif(win32)` |
| `test_status.py` — watcher heartbeat | Windows backslashes in YAML double-quoted string → escape sequence errors | `worker.as_posix()` for the path |
| `test_uninstall.py` | `/tmp` doesn't exist on Windows; `uninstall.py` hardcoded `/tmp` glob | `tempfile.gettempdir()` in both source and test |

#### Also in this session
- Deleted `feat/superharness-integration-morpheme` branch (local + remote) — cleared by Morpheme team
- Removed stale `/opt/homebrew/bin/superharness` (1.2.7) that was shadowing pipx install

---

## PRs Shipped

| PR | Title | Version |
|----|-------|---------|
| #103 | fix: Windows CI hang + os.kill sweep + 9 pre-existing test failures | 1.24.3 |

---

## Current State

- **Contract task `fix.windows-unit-test-hang`:** done
- **Only open task:** `feat.task-lifecycle-ship` (todo, blocked — auto-commit bypass risk)
- **superharness installed:** 1.24.3 via pipx
- **Branch:** main, clean

---

## Known Issues / Watch Points

- `feat.task-lifecycle-ship` remains blocked — the risk of auto-committing after task
  approval without human review is still unresolved. Do not start without a clear
  scope decision on what "ship step" means without bypassing review.
- Windows CI now completes (1448 passed, 0 failed, 296 skipped) — the 296 skips are
  intentional (`@_skip_win` guards on bash-dependent tests). That count is correct.

---

## Next Session Starting Point

```bash
shux status       # should show no issues
shux contract     # 1 open task: feat.task-lifecycle-ship
shux recall "windows os.kill"   # prior context for this fix if needed
```
