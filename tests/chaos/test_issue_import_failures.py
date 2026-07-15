"""Iteration 3: issue_import failure surface — missing CLI, nonzero exit, bad JSON."""
from __future__ import annotations

import subprocess

import pytest


def test_missing_cli_errors_cleanly(monkeypatch):
    from superharness.commands import issue_import

    monkeypatch.setattr(issue_import.shutil, "which", lambda _bin: None)
    with pytest.raises(RuntimeError, match="gh"):
        issue_import._fetch_issue("https://github.com/o/r/issues/5")


def test_cli_nonzero_exit_errors_cleanly(monkeypatch):
    from superharness.commands import issue_import

    monkeypatch.setattr(issue_import.shutil, "which", lambda _bin: "/usr/bin/gh")

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0], returncode=1, stdout="", stderr="issue not found"
        )

    monkeypatch.setattr(issue_import.subprocess, "run", _fake_run)
    with pytest.raises(RuntimeError, match="issue not found"):
        issue_import._fetch_issue("https://github.com/o/r/issues/5")


def test_malformed_json_errors_cleanly(monkeypatch):
    from superharness.commands import issue_import

    monkeypatch.setattr(issue_import.shutil, "which", lambda _bin: "/usr/bin/gh")

    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout="not json", stderr=""
        )

    monkeypatch.setattr(issue_import.subprocess, "run", _fake_run)
    with pytest.raises(RuntimeError, match="JSON"):
        issue_import._fetch_issue("https://github.com/o/r/issues/5")
