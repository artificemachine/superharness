"""Interactive prompt primitives for superharness CLI wizards.

Ported from hermes_cli/setup.py (sections #7 prompt primitives).
No app-specific dependencies — replace ANSI constants if needed.
"""
from __future__ import annotations

import getpass
import sys
from typing import Optional

import logging
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"


def _c(code: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{code}{text}{_RESET}"


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def print_header(title: str) -> None:
    print(f"\n{_c(_CYAN + _BOLD, f'◆ {title}')}")


def print_info(text: str) -> None:
    print(f"  {_c(_DIM, text)}")


def print_success(text: str) -> None:
    print(f"{_c(_GREEN, f'✓ {text}')}")


def print_warning(text: str) -> None:
    print(f"{_c(_YELLOW, f'⚠ {text}')}")


def print_error(text: str) -> None:
    print(f"{_c(_RED, f'✗ {text}')}")


# ---------------------------------------------------------------------------
# TTY detection
# ---------------------------------------------------------------------------

def is_interactive_stdin() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except Exception as e:
        logger.warning("prompts.py unexpected error: %s", e, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# prompt()
# ---------------------------------------------------------------------------

def prompt(
    question: str,
    default: Optional[str] = None,
    password: bool = False,
) -> str:
    suffix = f" [{default}]" if default else ""
    label = f"{_c(_YELLOW, question + suffix)}: "
    try:
        if password:
            raw = getpass.getpass(label)
        else:
            raw = input(label)
        result = raw.strip()
        return result if result else (default or "")
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(1)


# ---------------------------------------------------------------------------
# prompt_yes_no()
# ---------------------------------------------------------------------------

def prompt_yes_no(question: str, default: bool = True) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    label = f"{_c(_YELLOW, f'{question} {hint}')}: "
    while True:
        try:
            raw = input(label).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print_warning("Please enter y or n.")


# ---------------------------------------------------------------------------
# Curses helpers (internal — mockable in tests)
# ---------------------------------------------------------------------------

def _curses_choice(question: str, choices: list[str], default: int) -> int:
    """Try curses arrow-key menu. Returns selected index, or -1 on failure/unavailability."""
    try:
        import curses
    except ImportError:
        return -1

    def _run(stdscr: "curses.window") -> int:
        curses.curs_set(0)
        try:
            curses.start_color()
            curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
            bold_green = curses.color_pair(1) | curses.A_BOLD
        except Exception as e:
            logger.warning("prompts.py unexpected error: %s", e, exc_info=True)
            bold_green = curses.A_BOLD
        current = default
        while True:
            stdscr.clear()
            _h, w = stdscr.getmaxyx()
            stdscr.addnstr(0, 0, question, w - 1)
            for i, choice in enumerate(choices):
                attr = bold_green if i == current else curses.A_NORMAL
                prefix = "→ " if i == current else "  "
                stdscr.addnstr(i + 2, 0, f"{prefix}{choice}", w - 1, attr)
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k")) and current > 0:
                current -= 1
            elif key in (curses.KEY_DOWN, ord("j")) and current < len(choices) - 1:
                current += 1
            elif key in (ord("\n"), ord("\r"), curses.KEY_ENTER):
                return current
            elif key in (ord("q"), 27):
                return default

    try:
        return curses.wrapper(_run)
    except Exception as e:
        logger.warning("prompts.py unexpected error: %s", e, exc_info=True)
        return -1


def _curses_checklist(
    title: str,
    items: list[str],
    pre_selected: list[int],
) -> Optional[list[int]]:
    """Try curses multi-select. Returns selected indices, or None on cancel/unavailability."""
    try:
        import curses
    except ImportError:
        return None

    def _run(stdscr: "curses.window") -> Optional[list[int]]:
        curses.curs_set(0)
        try:
            curses.start_color()
            curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
            bold_green = curses.color_pair(1) | curses.A_BOLD
        except Exception as e:
            logger.warning("prompts.py unexpected error: %s", e, exc_info=True)
            bold_green = curses.A_BOLD
        selected = set(pre_selected)
        current = 0
        hint = f"{title}  (Space=toggle, Enter=confirm, q=cancel)"
        while True:
            stdscr.clear()
            _h, w = stdscr.getmaxyx()
            stdscr.addnstr(0, 0, hint, w - 1)
            for i, item in enumerate(items):
                mark = "[x]" if i in selected else "[ ]"
                attr = bold_green if i == current else curses.A_NORMAL
                stdscr.addnstr(i + 2, 0, f"{mark} {item}", w - 1, attr)
            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k")) and current > 0:
                current -= 1
            elif key in (curses.KEY_DOWN, ord("j")) and current < len(items) - 1:
                current += 1
            elif key == ord(" "):
                selected.discard(current) if current in selected else selected.add(current)
            elif key in (ord("\n"), ord("\r"), curses.KEY_ENTER):
                return sorted(selected)
            elif key in (ord("q"), 27):
                return None

    try:
        return curses.wrapper(_run)
    except Exception as e:
        logger.warning("prompts.py unexpected error: %s", e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# prompt_choice()
# ---------------------------------------------------------------------------

def prompt_choice(
    question: str,
    choices: list[str],
    default: int = 0,
) -> int:
    idx = _curses_choice(question, choices, default)
    if idx >= 0:
        return idx

    # Numbered fallback
    print(f"\n{_c(_YELLOW, question)}")
    for i, choice in enumerate(choices):
        marker = " (default)" if i == default else ""
        print(f"  {i + 1}. {choice}{marker}")

    while True:
        try:
            raw = input(f"Select [1-{len(choices)}] (default {default + 1}): ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)
        if not raw:
            print_info("Skipped (keeping current)")
            return default
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(choices):
                return n - 1
        print_warning(f"Enter a number between 1 and {len(choices)}.")


# ---------------------------------------------------------------------------
# prompt_checklist()
# ---------------------------------------------------------------------------

def prompt_checklist(
    title: str,
    items: list[str],
    pre_selected: Optional[list[int]] = None,
) -> list[int]:
    pre = pre_selected or []
    result = _curses_checklist(title, items, pre)
    if result is None:
        return list(pre)
    return result
