"""Single seam for process-liveness checks.

`os.kill(pid, 0)` is a correct liveness probe on POSIX, but on Windows it does
not query the process at all: CPython special-cases signal `0`
(`CTRL_C_EVENT`) and `1` (`CTRL_BREAK_EVENT`) to `GenerateConsoleCtrlEvent`,
which sends a console control event to the target's process group rather
than probing it. A detached/adopted process that is not in the caller's
console process group raises `OSError` from that call, which a naive
`except OSError: return False` then reports as "dead" even though the
process is alive. `pid_alive` is the only place in this codebase allowed to
contain this Windows-vs-POSIX branching; every other call site must import
it from here rather than reimplementing it.
"""
from __future__ import annotations

import os


def pid_alive(pid: int) -> bool:
    """Return True iff `pid` refers to a live process.

    Never raises. `pid <= 0` is rejected up front: on POSIX, signalling pid 0
    targets the caller's own process group and signalling pid -1 targets
    every process the caller has permission to signal, neither of which is a
    meaningful liveness answer for a specific pid.
    """
    if pid <= 0:
        return False

    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong(STILL_ACTIVE)
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return exit_code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False  # no such process
    except PermissionError:
        return True  # process exists; we just lack permission to signal it
    except OSError:
        return False
    return True
