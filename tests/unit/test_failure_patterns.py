"""Tests for superharness.engine.failure_patterns."""
from __future__ import annotations

from pathlib import Path

import pytest


class TestMatchPatterns:
    def test_import_error_matched(self) -> None:
        from superharness.engine.failure_patterns import match_patterns
        results = match_patterns("ModuleNotFoundError: No module named 'yaml'")
        ids = [p.id for p in results]
        assert "import_error" in ids

    def test_timeout_matched(self) -> None:
        from superharness.engine.failure_patterns import match_patterns
        results = match_patterns("TimeoutError: operation timed out after 30s")
        ids = [p.id for p in results]
        assert "timeout" in ids

    def test_git_conflict_matched(self) -> None:
        from superharness.engine.failure_patterns import match_patterns
        results = match_patterns("CONFLICT (content): Merge conflict in foo.py\nAutomatic merge failed")
        ids = [p.id for p in results]
        assert "git_conflict" in ids

    def test_test_failure_matched(self) -> None:
        from superharness.engine.failure_patterns import match_patterns
        results = match_patterns("FAILED tests/unit/test_foo.py::test_bar - AssertionError")
        ids = [p.id for p in results]
        assert "test_failure" in ids

    def test_no_match_returns_empty(self) -> None:
        from superharness.engine.failure_patterns import match_patterns
        results = match_patterns("everything completed successfully")
        assert results == []

    def test_empty_string_returns_empty(self) -> None:
        from superharness.engine.failure_patterns import match_patterns
        results = match_patterns("")
        assert results == []

    def test_multiple_patterns_can_match(self) -> None:
        from superharness.engine.failure_patterns import match_patterns
        # Text with both a test failure and an assertion
        results = match_patterns("AssertionError: assert 1 == 2\nFAILED tests/unit/test_x.py")
        ids = [p.id for p in results]
        assert "test_failure" in ids

    def test_case_insensitive_match(self) -> None:
        from superharness.engine.failure_patterns import match_patterns
        results = match_patterns("permission denied: /var/log/foo")
        ids = [p.id for p in results]
        assert "permission_denied" in ids

    def test_syntax_error_matched(self) -> None:
        from superharness.engine.failure_patterns import match_patterns
        results = match_patterns("SyntaxError: invalid syntax (file.py, line 5)")
        ids = [p.id for p in results]
        assert "syntax_error" in ids

    def test_yaml_parse_matched(self) -> None:
        from superharness.engine.failure_patterns import match_patterns
        results = match_patterns("yaml.scanner.ScannerError: mapping values are not allowed here")
        ids = [p.id for p in results]
        assert "yaml_parse" in ids

    def test_api_auth_matched(self) -> None:
        from superharness.engine.failure_patterns import match_patterns
        results = match_patterns("AuthenticationError: invalid api key provided")
        ids = [p.id for p in results]
        assert "api_auth" in ids


def _read_failures_sqlite(project_dir: Path) -> list[dict]:
    """Post-migration: failures live in SQLite. Read them and return
    a list of dicts in the legacy YAML shape so test assertions remain
    readable."""
    import sqlite3 as _sql
    db = _sql.connect(str(project_dir / ".superharness" / "state.sqlite3"))
    rows = db.execute(
        "SELECT task_id, agent, pattern, error_snippet FROM failures "
        "ORDER BY created_at"
    ).fetchall()
    db.close()
    return [
        {"task": r[0], "agent": r[1], "patterns": (r[2] or "").split(","),
         "error_snippet": r[3]}
        for r in rows
    ]


class TestRecordFailure:
    def test_records_to_failures_yaml(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure
        from superharness.engine.db import get_connection, init_db
        sh = tmp_path / ".superharness"
        sh.mkdir()
        # Init SQLite (post-migration source of truth).
        _c = get_connection(str(tmp_path)); init_db(_c, str(tmp_path)); _c.close()

        matched = record_failure(str(tmp_path), "task-1", "ModuleNotFoundError: No module named foo")
        ids = [p.id for p in matched]
        assert "import_error" in ids

        data = _read_failures_sqlite(tmp_path)
        assert len(data) == 1
        entry = data[0]
        assert entry["task"] == "task-1"
        assert "import_error" in entry["patterns"]

    def test_extra_dict_injection_blocked(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure
        from superharness.engine.db import get_connection, init_db
        sh = tmp_path / ".superharness"
        sh.mkdir()
        _c = get_connection(str(tmp_path)); init_db(_c, str(tmp_path)); _c.close()

        record_failure(str(tmp_path), "task-inject", "ImportError",
                       extra={"task": "evil", "agent": "hacker", "context": "legit-context"})
        data = _read_failures_sqlite(tmp_path)
        entry = data[0]
        # Core fields must NOT be overwritten by extra dict
        assert entry["task"] == "task-inject"
        assert entry["agent"] == "claude-code"

    def test_unknown_pattern_recorded(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure
        from superharness.engine.db import get_connection, init_db
        sh = tmp_path / ".superharness"
        sh.mkdir()
        _c = get_connection(str(tmp_path)); init_db(_c, str(tmp_path)); _c.close()

        matched = record_failure(str(tmp_path), "task-2", "some completely unrecognized error output")
        assert matched == []

        data = _read_failures_sqlite(tmp_path)
        entry = data[0]
        assert "unknown" in entry["patterns"]

    def test_multiple_entries_accumulate(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure
        from superharness.engine.db import get_connection, init_db
        sh = tmp_path / ".superharness"
        sh.mkdir()
        _c = get_connection(str(tmp_path)); init_db(_c, str(tmp_path)); _c.close()

        record_failure(str(tmp_path), "task-3", "TimeoutError: deadline exceeded")
        record_failure(str(tmp_path), "task-3", "SyntaxError: invalid syntax")

        data = _read_failures_sqlite(tmp_path)
        assert len(data) == 2

    def test_creates_failures_file_if_missing(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure
        from superharness.engine.db import get_connection, init_db
        sh = tmp_path / ".superharness"
        sh.mkdir()
        # SQLite is created on demand by record_failure; no pre-init needed.
        _c = get_connection(str(tmp_path)); init_db(_c, str(tmp_path)); _c.close()
        record_failure(str(tmp_path), "task-4", "ImportError: no module")
        # Failure landed in SQLite even though there is no failures.yaml.
        data = _read_failures_sqlite(tmp_path)
        assert len(data) == 1
        assert (sh / "state.sqlite3").exists()


class TestGetFailureHints:
    def test_returns_hints_for_known_task(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure, get_failure_hints
        sh = tmp_path / ".superharness"
        sh.mkdir()
        (sh / "failures.yaml").write_text("failures: []\n")

        record_failure(str(tmp_path), "feat.my-task", "ImportError: No module named foo")
        hints = get_failure_hints(str(tmp_path), "feat.my-task")
        assert len(hints) >= 1
        assert any("import" in h.lower() or "pip install" in h.lower() for h in hints)

    def test_returns_empty_for_unknown_task(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import get_failure_hints
        sh = tmp_path / ".superharness"
        sh.mkdir()
        (sh / "failures.yaml").write_text("failures: []\n")

        hints = get_failure_hints(str(tmp_path), "task-never-failed")
        assert hints == []

    def test_deduplicates_same_pattern(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure, get_failure_hints
        sh = tmp_path / ".superharness"
        sh.mkdir()
        (sh / "failures.yaml").write_text("failures: []\n")

        # Same pattern recorded twice
        record_failure(str(tmp_path), "dup-task", "TimeoutError: timed out")
        record_failure(str(tmp_path), "dup-task", "TimeoutError: budget exceeded")
        hints = get_failure_hints(str(tmp_path), "dup-task")
        # Should only have one hint for timeout
        timeout_hints = [h for h in hints if "timeout" in h.lower() or "timed" in h.lower() or "budget" in h.lower()]
        assert len(timeout_hints) == 1

    def test_remediation_included_when_present(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure, get_failure_hints
        sh = tmp_path / ".superharness"
        sh.mkdir()
        (sh / "failures.yaml").write_text("failures: []\n")

        record_failure(str(tmp_path), "fix-task", "ImportError: cannot import name X")
        hints = get_failure_hints(str(tmp_path), "fix-task")
        # import_error has a remediation
        assert any("pip install" in h for h in hints)


class TestStripAnsi:
    def test_strip_ansi_basic(self) -> None:
        from superharness.engine.failure_patterns import strip_ansi
        text = "\x1b[31mError:\x1b[0m critical failure"
        assert strip_ansi(text) == "Error: critical failure"

    def test_strip_ansi_complex(self) -> None:
        from superharness.engine.failure_patterns import strip_ansi
        # Contains multiple sequences, including movements and styles
        text = "\x1b[1;32mSUCCESS\x1b[0m \x1b[34m[task-123]\x1b[0m \x1b[K"
        assert strip_ansi(text).strip() == "SUCCESS [task-123]"

    def test_strip_terminal_noise(self) -> None:
        from superharness.engine.failure_patterns import strip_ansi
        # BEL (\x07) and BS (\x08)
        text = "Loading...\x07\x08\x08\x08Done"
        assert strip_ansi(text) == "Loading...Done"

