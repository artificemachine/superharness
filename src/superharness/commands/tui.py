"""
superharness TUI — terminal board for real-time task and agent monitoring.

Usage:
    shux tui [--project PATH] [--refresh SECONDS] [--no-color]

Keyboard shortcuts (board mode):
    h/l or ←/→    move between columns
    j/k or ↑/↓    move between tasks in column
    Enter          open task detail
    a              approve plan (plan_proposed → plan_approved)
    r              reject report (report_ready → review_failed)
    p              pause in-progress task
    d              delegate task (enqueue for dispatch)
    D              view discussions
    H              toggle agent health panel
    /              search/filter tasks
    Esc            back / clear search
    R              force refresh
    q              quit

In search mode:
    type to filter, Enter to confirm, Esc to cancel

In detail mode:
    j/k            scroll detail
    Esc / q        back to board
"""
from __future__ import annotations

import os
import sys
import time
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

import logging
logger = logging.getLogger(__name__)


# ── Column definitions ───────────────────────────────────────────────────────

COLUMNS: list[tuple[str, list[str]]] = [
    ("TODO",   ["todo"]),
    ("PLAN",   ["plan_proposed", "plan_approved"]),
    ("ACTIVE", ["in_progress", "launched", "running"]),
    ("REVIEW", ["report_ready", "review_requested", "review_passed", "review_failed"]),
    ("DONE",   ["done", "failed", "archived", "stopped", "cancelled"]),
]

_COL_KEYS = [c[0].lower() for c in COLUMNS]  # todo, plan, active, review, done

_STATUS_TO_COL: dict[str, str] = {}
for _col_label, _statuses in COLUMNS:
    for _s in _statuses:
        _STATUS_TO_COL[_s] = _col_label.lower()

# Status → color name
_STATUS_COLOR: dict[str, str] = {
    "todo":             "white",
    "plan_proposed":    "yellow",
    "plan_approved":    "cyan",
    "in_progress":      "blue",
    "launched":         "blue",
    "running":          "blue",
    "report_ready":     "magenta",
    "review_requested": "magenta",
    "review_passed":    "green",
    "review_failed":    "red",
    "done":             "green",
    "failed":           "red",
    "archived":         "white",
    "stopped":          "red",
    "cancelled":        "white",
}


# ── Pure data functions (testable without curses) ─────────────────────────────

def status_color_name(status: str) -> str:
    """Return a color name for a task status."""
    return _STATUS_COLOR.get(status, "white")


def categorize_tasks(tasks: list[dict]) -> dict[str, list[dict]]:
    """Group tasks into board columns."""
    result: dict[str, list[dict]] = {k: [] for k in _COL_KEYS}
    for task in tasks:
        st = str(task.get("status", "todo"))
        col = _STATUS_TO_COL.get(st, "todo")
        result[col].append(task)
    return result


def filter_tasks(tasks: list[dict], query: str) -> list[dict]:
    """Filter tasks by query — matches id, title, or owner (case-insensitive)."""
    if not query:
        return tasks
    q = query.lower()
    return [
        t for t in tasks
        if q in str(t.get("id", "")).lower()
        or q in str(t.get("title", "")).lower()
        or q in str(t.get("owner", "")).lower()
    ]


def get_column_tasks(cats: dict[str, list[dict]], state: "TuiState") -> list[dict]:
    """Return the task list for the currently focused column."""
    col_key = _COL_KEYS[state.col_idx]
    return cats.get(col_key, [])


def _can_approve(task: dict) -> bool:
    return task.get("status") == "plan_proposed"


def _can_reject(task: dict) -> bool:
    return task.get("status") in {"report_ready", "review_requested"}


def _can_pause(task: dict) -> bool:
    return task.get("status") in {"in_progress", "launched", "running"}


def _can_delegate(task: dict) -> bool:
    return task.get("status") in {"todo", "plan_approved"}


# ── State ────────────────────────────────────────────────────────────────────

@dataclass
class TuiState:
    col_idx: int = 0
    row_idx: int = 0
    mode: str = "board"          # board | detail | discussions | health | search
    search_query: str = ""
    searching: bool = False
    refresh_interval: int = 5
    last_refresh: float = 0.0
    message: str = ""
    detail_scroll: int = 0
    show_health: bool = False
    show_discussions: bool = False


# ── Color helpers ─────────────────────────────────────────────────────────────

_COLOR_PAIR: dict[str, int] = {}  # name → curses pair number

def _init_colors(curses) -> None:
    """Initialize color pairs. Called once after curses.start_color()."""
    curses.use_default_colors()
    pairs = [
        (1, "white",   curses.COLOR_WHITE,   -1),
        (2, "green",   curses.COLOR_GREEN,   -1),
        (3, "yellow",  curses.COLOR_YELLOW,  -1),
        (4, "blue",    curses.COLOR_CYAN,    -1),   # cyan reads better than blue in most terms
        (5, "magenta", curses.COLOR_MAGENTA, -1),
        (6, "cyan",    curses.COLOR_CYAN,    -1),
        (7, "red",     curses.COLOR_RED,     -1),
        (8, "header",  curses.COLOR_BLACK,   curses.COLOR_CYAN),
        (9, "select",  curses.COLOR_BLACK,   curses.COLOR_WHITE),
        (10, "dim",    curses.COLOR_WHITE,   -1),
    ]
    for num, name, fg, bg in pairs:
        try:
            curses.init_pair(num, fg, bg)
            _COLOR_PAIR[name] = num
        except Exception as e:
            logger.warning("tui.py unexpected error: %s", e, exc_info=True)
            _COLOR_PAIR[name] = 0


def _attr(curses, name: str, bold: bool = False) -> int:
    """Return curses attribute for a color name."""
    pair = _COLOR_PAIR.get(name, 0)
    attr = curses.color_pair(pair) if pair else 0
    if bold:
        attr |= curses.A_BOLD
    return attr


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_snapshot(project_dir: str) -> dict:
    """Load the dashboard snapshot from SQLite. Returns empty dict on failure."""
    try:
        from superharness.engine import db as _db
        from superharness.engine.dashboard_presenter import get_dashboard_status_snapshot
        conn = _db.get_connection(project_dir)
        _db.ensure_schema(conn, project_dir)
        snap = get_dashboard_status_snapshot(conn, project_dir)
        conn.close()
        return snap
    except Exception as e:
        return {"_error": str(e), "contract_tasks": [], "active_discussions": []}


def _load_agent_health(project_dir: str) -> dict:
    """Return agent heartbeat / health info."""
    health: dict[str, str] = {}
    try:
        from superharness.engine.agent_status import get_all_agent_statuses
        for name, status in get_all_agent_statuses(project_dir).items():
            health[name] = status
    except Exception as e:
        logger.warning("tui.py unexpected error: %s", e, exc_info=True)
        pass
    # watcher check via watcher_singleton
    try:
        from superharness.engine import watcher_singleton
        health["watcher"] = "running" if watcher_singleton.is_running(project_dir) else "stopped"
    except Exception as e:
        logger.warning("tui.py unexpected error: %s", e, exc_info=True)
        health["watcher"] = "unknown"

    return health


# ── Action dispatch ───────────────────────────────────────────────────────────

def _run_shux(args: list[str], project_dir: str) -> tuple[int, str]:
    """Run a shux subcommand and return (returncode, output)."""
    result = subprocess.run(
        [sys.executable, "-m", "superharness.cli"] + args + ["--project", project_dir],
        capture_output=True, text=True,
    )
    out = (result.stdout + result.stderr).strip()
    return result.returncode, out


def action_approve(task: dict, project_dir: str) -> str:
    """Approve a plan_proposed task."""
    if not _can_approve(task):
        return f"Cannot approve task in status '{task.get('status')}'"
    rc, out = _run_shux(["task", "status", "--id", task["id"], "--status", "plan_approved",
                          "--actor", "operator", "--summary", "Approved via TUI"], project_dir)
    return out if out else ("Approved" if rc == 0 else "Failed to approve")


def action_reject(task: dict, project_dir: str) -> str:
    """Reject a report_ready task (review_failed)."""
    if not _can_reject(task):
        return f"Cannot reject task in status '{task.get('status')}'"
    rc, out = _run_shux(["task", "status", "--id", task["id"], "--status", "review_failed",
                          "--actor", "operator", "--summary", "Rejected via TUI"], project_dir)
    return out if out else ("Rejected" if rc == 0 else "Failed to reject")


def action_pause(task: dict, project_dir: str) -> str:
    """Pause an in-progress task."""
    if not _can_pause(task):
        return f"Cannot pause task in status '{task.get('status')}'"
    rc, out = _run_shux(["task", "status", "--id", task["id"], "--status", "stopped",
                          "--actor", "operator", "--summary", "Paused via TUI"], project_dir)
    return out if out else ("Paused" if rc == 0 else "Failed to pause")


def action_delegate(task: dict, project_dir: str) -> str:
    """Delegate a task to its assigned agent."""
    if not _can_delegate(task):
        return f"Cannot delegate task in status '{task.get('status')}'"
    rc, out = _run_shux(["delegate", task["id"]], project_dir)
    return out if out else ("Delegated" if rc == 0 else "Failed to delegate")


# ── Rendering ─────────────────────────────────────────────────────────────────

def _draw_header(stdscr, curses, project_dir: str, state: TuiState, width: int) -> None:
    proj_name = os.path.basename(project_dir)
    ts = time.strftime("%H:%M:%S")
    mode_hint = f"  [{state.mode}]" if state.mode != "board" else ""
    title = f" superharness TUI  |  {proj_name}  |  {ts}{mode_hint}"
    title = title[:width - 1].ljust(width - 1)
    try:
        stdscr.addstr(0, 0, title, _attr(curses, "header", bold=True))
    except curses.error:
        pass


def _draw_footer(stdscr, curses, state: TuiState, height: int, width: int) -> None:
    if state.searching:
        hint = f" Search: {state.search_query}_"
    elif state.message:
        hint = f" {state.message}"
    elif state.mode == "detail":
        hint = " j/k:scroll  Esc/q:back"
    elif state.mode == "discussions":
        hint = " j/k:scroll  Esc/q:back"
    elif state.mode == "health":
        hint = " Esc/H:back  q:quit"
    else:
        hint = " ←→:col  ↑↓:task  a:approve  r:reject  p:pause  d:delegate  D:discuss  H:health  /:search  R:refresh  q:quit"
    hint = hint[:width - 1].ljust(width - 1)
    try:
        stdscr.addstr(height - 1, 0, hint, _attr(curses, "header"))
    except curses.error:
        pass


def _draw_board(stdscr, curses, cats: dict, state: TuiState, height: int, width: int) -> None:
    """Draw the 5-column Kanban board."""
    board_height = height - 4  # header (1) + column headers (2) + footer (1)
    board_top = 2
    col_count = len(COLUMNS)
    col_width = max(10, width // col_count)

    # Column headers
    for ci, (label, _) in enumerate(COLUMNS):
        x = ci * col_width
        col_key = label.lower()
        count = len(cats.get(col_key, []))
        hdr = f" {label} ({count}) ".center(col_width - 1)[:col_width - 1]
        attr = _attr(curses, "header", bold=True) if ci == state.col_idx else _attr(curses, "dim")
        try:
            stdscr.addstr(1, x, hdr, attr)
        except curses.error:
            pass

    # Separator
    try:
        stdscr.addstr(board_top - 1, 0, "─" * (width - 1), _attr(curses, "dim"))
    except curses.error:
        pass

    # Tasks in each column
    for ci, (label, _) in enumerate(COLUMNS):
        x = ci * col_width
        col_key = label.lower()
        tasks = cats.get(col_key, [])

        # Apply search filter within each column if in search mode
        if state.search_query:
            tasks = filter_tasks(tasks, state.search_query)

        for ri, task in enumerate(tasks[:board_height]):
            y = board_top + ri
            task_id = str(task.get("id", ""))
            task_title = str(task.get("title", task_id))
            status = str(task.get("status", "todo"))
            color = status_color_name(status)

            selected = (ci == state.col_idx and ri == state.row_idx)

            # Truncate to fit column
            max_len = col_width - 3
            line = f" {task_title}"[:max_len + 1].ljust(col_width - 1)

            if selected:
                attr = _attr(curses, "select", bold=True)
            else:
                attr = _attr(curses, color)

            try:
                stdscr.addstr(y, x, line, attr)
            except curses.error:
                pass

        # Fill remaining rows with blanks to clear stale content
        for ri in range(len(tasks[:board_height]), board_height):
            y = board_top + ri
            try:
                stdscr.addstr(y, x, " " * (col_width - 1))
            except curses.error:
                pass


def _draw_detail(stdscr, curses, task: Optional[dict], state: TuiState, height: int, width: int) -> None:
    """Draw task detail panel in the lower portion of the screen."""
    if not task:
        return
    panel_top = height - 12
    panel_height = 11
    if panel_top < 3:
        panel_top = 3
        panel_height = height - 4

    sep = "─" * (width - 1)
    try:
        stdscr.addstr(panel_top, 0, sep, _attr(curses, "dim"))
    except curses.error:
        pass

    lines = [
        f"  ID:     {task.get('id', '')}",
        f"  Title:  {task.get('title', '')}",
        f"  Owner:  {task.get('owner', '')}",
        f"  Status: {task.get('status', '')}",
        f"  Effort: {task.get('effort', '-')}",
    ]
    # Acceptance criteria
    ac = task.get("acceptance_criteria", [])
    if ac:
        lines.append("  Criteria:")
        for item in ac[:5]:
            lines.append(f"    • {item}")

    # TDD block
    tdd = task.get("tdd") or {}
    if tdd:
        red = str(tdd.get("red", ""))[:60]
        lines.append(f"  TDD red:  {red}")

    # Context
    ctx = task.get("context") or task.get("summary") or ""
    if ctx:
        lines.append(f"  Context: {ctx[:width - 14]}")

    # Actions hint
    available = []
    if _can_approve(task): available.append("a:approve")
    if _can_reject(task):  available.append("r:reject")
    if _can_pause(task):   available.append("p:pause")
    if _can_delegate(task): available.append("d:delegate")
    if available:
        lines.append(f"  Actions: {' | '.join(available)}")

    offset = state.detail_scroll
    visible_lines = lines[offset:offset + panel_height - 1]
    for i, line in enumerate(visible_lines):
        y = panel_top + 1 + i
        if y >= height - 1:
            break
        try:
            stdscr.addstr(y, 0, line[:width - 1].ljust(width - 1))
        except curses.error:
            pass


def _draw_discussions(stdscr, curses, discussions: list[dict], state: TuiState, height: int, width: int) -> None:
    """Overlay: discussion threads."""
    panel_top = 2
    sep = "═" * (width - 1)
    try:
        stdscr.addstr(panel_top, 0, sep, _attr(curses, "header"))
        stdscr.addstr(panel_top + 1, 0, "  DISCUSSIONS".ljust(width - 1), _attr(curses, "header", bold=True))
        stdscr.addstr(panel_top + 2, 0, sep, _attr(curses, "header"))
    except curses.error:
        pass

    if not discussions:
        try:
            stdscr.addstr(panel_top + 4, 2, "No active discussions.")
        except curses.error:
            pass
        return

    offset = state.detail_scroll
    y = panel_top + 4
    for disc in discussions[offset:]:
        if y >= height - 2:
            break
        topic = str(disc.get("topic", disc.get("id", "?")))
        status = str(disc.get("status", ""))
        participants = ", ".join(disc.get("participants") or [])
        line = f"  [{status}] {topic}  ({participants})"
        try:
            stdscr.addstr(y, 0, line[:width - 1])
        except curses.error:
            pass
        y += 1


def _draw_health(stdscr, curses, health: dict, state: TuiState, height: int, width: int) -> None:
    """Overlay: agent health panel."""
    panel_top = 2
    sep = "═" * (width - 1)
    try:
        stdscr.addstr(panel_top, 0, sep, _attr(curses, "header"))
        stdscr.addstr(panel_top + 1, 0, "  AGENT HEALTH".ljust(width - 1), _attr(curses, "header", bold=True))
        stdscr.addstr(panel_top + 2, 0, sep, _attr(curses, "header"))
    except curses.error:
        pass

    y = panel_top + 4
    if not health:
        try:
            stdscr.addstr(y, 2, "No health data available.")
        except curses.error:
            pass
        return

    for name, status in sorted(health.items()):
        if y >= height - 2:
            break
        color = "green" if "running" in status or "ok" in status or "active" in status else "red"
        icon = "●" if color == "green" else "○"
        line = f"  {icon} {name:<20} {status}"
        try:
            stdscr.addstr(y, 0, line[:width - 1], _attr(curses, color))
        except curses.error:
            pass
        y += 1


# ── Key handling ──────────────────────────────────────────────────────────────

def handle_key(key: int, state: TuiState, cats: dict, snapshot: dict, project_dir: str, curses) -> bool:
    """Process a keypress. Returns True if TUI should exit.

    State is mutated in place.
    """
    KEY_UP    = curses.KEY_UP
    KEY_DOWN  = curses.KEY_DOWN
    KEY_LEFT  = curses.KEY_LEFT
    KEY_RIGHT = curses.KEY_RIGHT
    KEY_ENTER = ord("\n")
    KEY_ESC   = 27

    state.message = ""  # clear status bar on each keypress

    # ── Search mode ──────────────────────────────────────────────────────────
    if state.searching:
        if key == KEY_ESC or key == 7:  # 7 = Ctrl-G
            state.searching = False
            state.search_query = ""
        elif key in (KEY_ENTER, curses.KEY_ENTER):
            state.searching = False
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            state.search_query = state.search_query[:-1]
        elif 32 <= key < 127:
            state.search_query += chr(key)
        return False

    # ── Detail / overlay modes ───────────────────────────────────────────────
    if state.mode in ("detail", "discussions", "health"):
        if key in (KEY_ESC, ord("q"), ord("b")):
            state.mode = "board"
            state.detail_scroll = 0
        elif key in (ord("j"), KEY_DOWN):
            state.detail_scroll += 1
        elif key in (ord("k"), KEY_UP):
            state.detail_scroll = max(0, state.detail_scroll - 1)
        return False

    # ── Board mode ────────────────────────────────────────────────────────────
    col_tasks = get_column_tasks(cats, state)
    if state.search_query:
        col_tasks = filter_tasks(col_tasks, state.search_query)

    # Navigation
    if key in (KEY_LEFT, ord("h")):
        state.col_idx = max(0, state.col_idx - 1)
        state.row_idx = 0
    elif key in (KEY_RIGHT, ord("l")):
        state.col_idx = min(len(COLUMNS) - 1, state.col_idx + 1)
        state.row_idx = 0
    elif key in (KEY_UP, ord("k")):
        state.row_idx = max(0, state.row_idx - 1)
    elif key in (KEY_DOWN, ord("j")):
        max_row = max(0, len(col_tasks) - 1)
        state.row_idx = min(max_row, state.row_idx + 1)

    # Open detail
    elif key in (KEY_ENTER, curses.KEY_ENTER, ord(" ")):
        if col_tasks and state.row_idx < len(col_tasks):
            state.mode = "detail"
            state.detail_scroll = 0

    # Actions
    elif key == ord("a"):
        if col_tasks and state.row_idx < len(col_tasks):
            task = col_tasks[state.row_idx]
            state.message = action_approve(task, project_dir)
            state.last_refresh = 0  # force reload
    elif key == ord("r"):
        if col_tasks and state.row_idx < len(col_tasks):
            task = col_tasks[state.row_idx]
            state.message = action_reject(task, project_dir)
            state.last_refresh = 0
    elif key == ord("p"):
        if col_tasks and state.row_idx < len(col_tasks):
            task = col_tasks[state.row_idx]
            state.message = action_pause(task, project_dir)
            state.last_refresh = 0
    elif key == ord("d"):
        if col_tasks and state.row_idx < len(col_tasks):
            task = col_tasks[state.row_idx]
            state.message = action_delegate(task, project_dir)
            state.last_refresh = 0

    # Overlays
    elif key == ord("D"):
        state.mode = "discussions"
        state.detail_scroll = 0
    elif key == ord("H"):
        state.mode = "health"
        state.detail_scroll = 0

    # Search
    elif key == ord("/"):
        state.searching = True
        state.search_query = ""

    # Refresh
    elif key == ord("R"):
        state.last_refresh = 0

    # Quit
    elif key in (ord("q"), ord("Q")):
        return True

    return False


# ── Main TUI loop ─────────────────────────────────────────────────────────────

def _tui_main(stdscr, project_dir: str, refresh_interval: int, no_color: bool) -> None:
    """Main curses entry point."""
    import curses

    curses.curs_set(0)  # hide cursor
    if curses.has_colors() and not no_color:
        curses.start_color()
        _init_colors(curses)

    state = TuiState(refresh_interval=refresh_interval)
    snapshot: dict = {}
    cats: dict = {k: [] for k in _COL_KEYS}
    health: dict = {}

    while True:
        now = time.monotonic()

        # Auto-refresh
        if now - state.last_refresh >= state.refresh_interval:
            snapshot = _load_snapshot(project_dir)
            all_tasks = snapshot.get("contract_tasks", [])
            cats = categorize_tasks(all_tasks)
            if state.show_health or state.mode == "health":
                health = _load_agent_health(project_dir)
            state.last_refresh = now

        # Render
        try:
            height, width = stdscr.getmaxyx()
            stdscr.erase()

            _draw_header(stdscr, curses, project_dir, state, width)

            if state.mode == "detail":
                # Show board + detail panel
                col_tasks = get_column_tasks(cats, state)
                if state.search_query:
                    col_tasks = filter_tasks(col_tasks, state.search_query)
                selected_task = col_tasks[state.row_idx] if col_tasks and state.row_idx < len(col_tasks) else None
                _draw_board(stdscr, curses, cats, state, height // 2 + 2, width)
                _draw_detail(stdscr, curses, selected_task, state, height, width)
            elif state.mode == "discussions":
                _draw_board(stdscr, curses, cats, state, height, width)
                _draw_discussions(stdscr, curses, snapshot.get("active_discussions", []), state, height, width)
            elif state.mode == "health":
                _draw_board(stdscr, curses, cats, state, height, width)
                _draw_health(stdscr, curses, health, state, height, width)
            else:
                _draw_board(stdscr, curses, cats, state, height, width)

            _draw_footer(stdscr, curses, state, height, width)
            stdscr.refresh()
        except curses.error:
            pass

        # Key input (non-blocking, 500 ms timeout so refresh fires)
        stdscr.timeout(500)
        key = stdscr.getch()
        if key == -1:
            continue

        if handle_key(key, state, cats, snapshot, project_dir, curses):
            break


def run_tui(project_dir: str, refresh_interval: int = 5, no_color: bool = False) -> None:
    """Entry point — launches curses wrapper or prints error on unsupported platforms."""
    try:
        import curses as _curses
        _curses.wrapper(_tui_main, project_dir, refresh_interval, no_color)
    except ModuleNotFoundError:
        print("curses is not available on this platform. TUI requires a Unix/macOS terminal.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass


# ── CLI entry point ───────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    import argparse
    parser = argparse.ArgumentParser(
        prog="shux tui",
        description="superharness terminal board",
    )
    parser.add_argument("--project", "-p", default=None,
                        help="Project directory (default: cwd)")
    parser.add_argument("--refresh", "-r", type=int, default=5,
                        help="Auto-refresh interval in seconds (default: 5)")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable colors")
    args = parser.parse_args(argv)

    project_dir = os.path.realpath(args.project or os.getcwd())
    harness_dir = os.path.join(project_dir, ".superharness")
    if not os.path.isdir(harness_dir):
        print(f"Error: {harness_dir} not found. Run 'shux init' first.", file=sys.stderr)
        sys.exit(1)

    run_tui(project_dir, refresh_interval=args.refresh, no_color=args.no_color)


if __name__ == "__main__":
    main()
