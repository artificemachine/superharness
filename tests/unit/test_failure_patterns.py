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


class TestRecordFailure:
    def test_records_to_failures_yaml(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure, _load_failures
        sh = tmp_path / ".superharness"
        sh.mkdir()
        (sh / "failures.yaml").write_text("failures: []\n")

        matched = record_failure(str(tmp_path), "task-1", "ModuleNotFoundError: No module named foo")
        ids = [p.id for p in matched]
        assert "import_error" in ids

        data = _load_failures(str(sh / "failures.yaml"))
        assert len(data["failures"]) == 1
        entry = data["failures"][0]
        assert entry["task"] == "task-1"
        assert "import_error" in entry["patterns"]

    def test_extra_dict_injection_blocked(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure, _load_failures
        sh = tmp_path / ".superharness"
        sh.mkdir()
        (sh / "failures.yaml").write_text("failures: []\n")

        record_failure(str(tmp_path), "task-inject", "ImportError",
                       extra={"task": "evil", "agent": "hacker", "context": "legit-context"})
        data = _load_failures(str(sh / "failures.yaml"))
        entry = data["failures"][0]
        # Core fields must NOT be overwritten
        assert entry["task"] == "task-inject"
        assert entry["agent"] == "claude-code"
        # Safe extra keys are allowed
        assert entry.get("context") == "legit-context"

    def test_unknown_pattern_recorded(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure, _load_failures
        sh = tmp_path / ".superharness"
        sh.mkdir()
        (sh / "failures.yaml").write_text("failures: []\n")

        matched = record_failure(str(tmp_path), "task-2", "some completely unrecognized error output")
        assert matched == []

        data = _load_failures(str(sh / "failures.yaml"))
        entry = data["failures"][0]
        assert "unknown" in entry["patterns"]

    def test_multiple_entries_accumulate(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure, _load_failures
        sh = tmp_path / ".superharness"
        sh.mkdir()
        (sh / "failures.yaml").write_text("failures: []\n")

        record_failure(str(tmp_path), "task-3", "TimeoutError: deadline exceeded")
        record_failure(str(tmp_path), "task-3", "SyntaxError: invalid syntax")

        data = _load_failures(str(sh / "failures.yaml"))
        assert len(data["failures"]) == 2

    def test_creates_failures_file_if_missing(self, tmp_path: Path) -> None:
        from superharness.engine.failure_patterns import record_failure
        sh = tmp_path / ".superharness"
        sh.mkdir()
        # No failures.yaml yet
        record_failure(str(tmp_path), "task-4", "ImportError: no module")
        assert (sh / "failures.yaml").exists()


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
