"""Tests for superharness.ui.prompts — RED phase for I1."""
from __future__ import annotations

import subprocess
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from superharness.ui.prompts import (
    is_interactive_stdin,
    prompt,
    prompt_choice,
    prompt_yes_no,
    prompt_checklist,
    print_header,
    print_info,
    print_success,
    print_warning,
    print_error,
)


# ---------------------------------------------------------------------------
# print helpers — smoke only (no crash, correct prefix)
# ---------------------------------------------------------------------------

def test_print_helpers_do_not_raise(capsys):
    print_header("Section")
    print_info("info text")
    print_success("success text")
    print_warning("warning text")
    print_error("error text")
    out = capsys.readouterr().out
    assert "Section" in out
    assert "info text" in out
    assert "success text" in out
    assert "warning text" in out
    assert "error text" in out


# ---------------------------------------------------------------------------
# prompt()
# ---------------------------------------------------------------------------

def test_prompt_returns_stripped_input():
    with patch("builtins.input", return_value="  hello  "):
        result = prompt("Question")
    assert result == "hello"


def test_prompt_returns_default_on_empty_input():
    with patch("builtins.input", return_value=""):
        result = prompt("Question", default="default-val")
    assert result == "default-val"


def test_prompt_returns_empty_string_when_no_default_and_empty():
    with patch("builtins.input", return_value=""):
        result = prompt("Question")
    assert result == ""


def test_prompt_uses_getpass_when_password():
    with patch("getpass.getpass", return_value="secret") as mock_gp:
        result = prompt("Key", password=True)
    mock_gp.assert_called_once()
    assert result == "secret"


def test_prompt_exits_on_keyboard_interrupt():
    with patch("builtins.input", side_effect=KeyboardInterrupt):
        with pytest.raises(SystemExit):
            prompt("Question")


def test_prompt_exits_on_eof_error():
    with patch("builtins.input", side_effect=EOFError):
        with pytest.raises(SystemExit):
            prompt("Question")


# ---------------------------------------------------------------------------
# prompt_yes_no()
# ---------------------------------------------------------------------------

def test_prompt_yes_no_default_true_empty_returns_true():
    with patch("builtins.input", return_value=""):
        assert prompt_yes_no("Continue?", default=True) is True


def test_prompt_yes_no_default_false_empty_returns_false():
    with patch("builtins.input", return_value=""):
        assert prompt_yes_no("Continue?", default=False) is False


def test_prompt_yes_no_explicit_yes():
    with patch("builtins.input", return_value="y"):
        assert prompt_yes_no("Continue?") is True


def test_prompt_yes_no_explicit_no():
    with patch("builtins.input", return_value="n"):
        assert prompt_yes_no("Continue?") is False


def test_prompt_yes_no_loops_on_bad_input():
    responses = iter(["maybe", "yes"])
    with patch("builtins.input", side_effect=lambda _: next(responses)):
        assert prompt_yes_no("Continue?") is True


def test_prompt_yes_no_exits_on_keyboard_interrupt():
    with patch("builtins.input", side_effect=KeyboardInterrupt):
        with pytest.raises(SystemExit):
            prompt_yes_no("Continue?")


# ---------------------------------------------------------------------------
# prompt_choice()
# ---------------------------------------------------------------------------

def test_prompt_choice_numbered_fallback_returns_correct_index():
    # curses disabled: numbered input path
    with patch("superharness.ui.prompts._curses_choice", return_value=-1):
        with patch("builtins.input", return_value="2"):
            idx = prompt_choice("Pick one", ["alpha", "beta", "gamma"])
    assert idx == 1  # 1-indexed input → 0-indexed result


def test_prompt_choice_enter_on_default_returns_default_index():
    with patch("superharness.ui.prompts._curses_choice", return_value=-1):
        with patch("builtins.input", return_value=""):
            idx = prompt_choice("Pick one", ["alpha", "beta", "gamma"], default=2)
    assert idx == 2


def test_prompt_choice_curses_path_returns_index():
    with patch("superharness.ui.prompts._curses_choice", return_value=1):
        idx = prompt_choice("Pick one", ["alpha", "beta", "gamma"])
    assert idx == 1


def test_prompt_choice_invalid_numbered_input_loops():
    responses = iter(["99", "abc", "1"])
    with patch("superharness.ui.prompts._curses_choice", return_value=-1):
        with patch("builtins.input", side_effect=lambda _: next(responses)):
            idx = prompt_choice("Pick one", ["alpha", "beta"])
    assert idx == 0


# ---------------------------------------------------------------------------
# prompt_checklist()
# ---------------------------------------------------------------------------

def test_prompt_checklist_returns_selected_indices():
    with patch("superharness.ui.prompts._curses_checklist", return_value=[0, 2]):
        result = prompt_checklist("Select", ["a", "b", "c"])
    assert result == [0, 2]


def test_prompt_checklist_cancel_returns_preselected():
    # curses cancel returns None → fall back to pre_selected
    with patch("superharness.ui.prompts._curses_checklist", return_value=None):
        result = prompt_checklist("Select", ["a", "b", "c"], pre_selected=[1])
    assert result == [1]


def test_prompt_checklist_cancel_with_no_preselected_returns_empty():
    with patch("superharness.ui.prompts._curses_checklist", return_value=None):
        result = prompt_checklist("Select", ["a", "b", "c"])
    assert result == []


# ---------------------------------------------------------------------------
# is_interactive_stdin()
# ---------------------------------------------------------------------------

def test_is_interactive_stdin_false_in_subprocess():
    """When stdin is a pipe (not a TTY), must return False."""
    code = (
        "from superharness.ui.prompts import is_interactive_stdin; "
        "import sys; sys.exit(0 if not is_interactive_stdin() else 1)"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        input=b"",
        capture_output=True,
    )
    assert r.returncode == 0, f"is_interactive_stdin returned True in a pipe: {r.stderr}"


def test_is_interactive_stdin_true_when_stdin_is_tty():
    with patch("sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = True
        assert is_interactive_stdin() is True


def test_is_interactive_stdin_false_when_stdin_has_no_isatty():
    with patch("sys.stdin", new=StringIO("data")):
        assert is_interactive_stdin() is False


# ---------------------------------------------------------------------------
# smoke test (importable + __main__ entry point)
# ---------------------------------------------------------------------------

def test_smoke_import():
    import superharness.ui.prompts  # noqa: F401
