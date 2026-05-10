"""Path helpers in discussion.py must work on Windows-style paths.

The Windows E2E tests (test_e2e_round_context_works_for_fresh_discussion,
test_discussion_auto_consensus_on_all_submissions, …) all failed with
"Discussion not found" because `_get_project_dir` did
`discussion_dir.rsplit("/.superharness/discussions/", 1)[0]`. On Windows
the separator is backslash, the rsplit returned the original string
unchanged, so the engine connected to a SQLite DB at the wrong path
(empty schema) and the discussion lookup returned None.
"""

from __future__ import annotations

from superharness.engine.discussion import _get_project_dir, _get_disc_id


def _eq_path(a: str, b: str) -> bool:
    """Path equality regardless of separator style — what matters is that
    the returned project_dir, once handed to os.path.join for SQLite I/O,
    resolves to the same location."""
    return a.replace("\\", "/").rstrip("/") == b.replace("\\", "/").rstrip("/")


class TestProjectDirExtraction:
    def test_posix_path(self):
        d = "/tmp/proj/.superharness/discussions/disc-abc"
        assert _eq_path(_get_project_dir(d), "/tmp/proj")

    def test_windows_backslash_path(self):
        d = r"C:\Users\runner\proj\.superharness\discussions\disc-abc"
        assert _eq_path(_get_project_dir(d), r"C:\Users\runner\proj")

    def test_windows_mixed_separators(self):
        d = r"C:\Users\runner\proj/.superharness/discussions/disc-abc"
        assert _eq_path(_get_project_dir(d), r"C:\Users\runner\proj")

    def test_trailing_separator_posix(self):
        assert _eq_path(_get_project_dir("/tmp/proj/.superharness/discussions/disc/"), "/tmp/proj")

    def test_returns_non_full_path_when_marker_missing(self):
        """If the path doesn't contain the marker, rsplit returns the full string.
        That's the existing contract — keep it; callers handle it elsewhere."""
        result = _get_project_dir("/tmp/some/random/path")
        assert _eq_path(result, "/tmp/some/random/path")


class TestDiscIdExtraction:
    def test_posix_path(self):
        assert _get_disc_id("/tmp/proj/.superharness/discussions/disc-abc") == "disc-abc"

    def test_windows_backslash_path(self):
        assert _get_disc_id(r"C:\Users\runner\proj\.superharness\discussions\disc-abc") == "disc-abc"

    def test_trailing_backslash(self):
        # On Windows os.path.basename strips trailing backslash; on POSIX it doesn't.
        # The rstrip in our helper covers both.
        result = _get_disc_id(r"C:\proj\.superharness\discussions\disc-abc\\")
        assert result == "disc-abc"

    def test_trailing_forward_slash(self):
        assert _get_disc_id("/tmp/proj/.superharness/discussions/disc-abc/") == "disc-abc"
