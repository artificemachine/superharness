"""Guards against the 2026-07-31 test-suite escape.

`.project-hooks/pre-commit` runs this suite, and git exports GIT_DIR (and
friends) into every hook's environment. Those variables take precedence over
both `cwd=` and `git -C`, so while any of them is set a correctly-scoped test
still operates on the real repository. That rewrote .git/config and pushed junk
commits and stashes into real history.

See docs/bugs/BUG-2026-07-31-test-suite-git-dir-escape.md.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from tests.conftest import _GIT_ENV_VARS


class TestGitEnvIsolation:
    @pytest.mark.parametrize("var", _GIT_ENV_VARS)
    def test_git_plumbing_var_not_set(self, var: str) -> None:
        """The autouse isolated_git_env fixture must scrub every one of them."""
        assert var not in os.environ, (
            f"{var} is set during the test run; git calls scoped with cwd= or "
            f"-C will silently retarget the repo it names"
        )

    def test_git_env_leak_would_redirect_a_scoped_call(self, tmp_path) -> None:
        """Pin the mechanism itself, so the reason for the fixture stays visible.

        With GIT_DIR set, `git -C <elsewhere> config` writes to GIT_DIR's repo,
        not to <elsewhere>. This asserts that precedence rather than trusting the
        prose in the bug report.
        """
        real = tmp_path / "real"
        decoy = tmp_path / "decoy"
        for path in (real, decoy):
            path.mkdir()
            subprocess.run(
                ["git", "init", "-q", str(path)], check=True, capture_output=True
            )

        subprocess.run(
            ["git", "-C", str(real), "config", "user.email", "real@real.com"],
            check=True,
            capture_output=True,
        )

        subprocess.run(
            ["git", "-C", str(decoy), "config", "user.email", "leaked@leaked.com"],
            check=True,
            capture_output=True,
            env={**os.environ, "GIT_DIR": str(real / ".git")},
        )

        landed = subprocess.run(
            ["git", "-C", str(real), "config", "--get", "user.email"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        assert landed == "leaked@leaked.com", (
            "GIT_DIR no longer overrides -C; if this ever fails, git changed its "
            "precedence rules and the isolated_git_env fixture can be revisited"
        )

    def test_scoped_call_stays_scoped_without_the_leak(self, tmp_path) -> None:
        """The same call is correctly contained once GIT_DIR is absent."""
        real = tmp_path / "real"
        decoy = tmp_path / "decoy"
        for path in (real, decoy):
            path.mkdir()
            subprocess.run(
                ["git", "init", "-q", str(path)], check=True, capture_output=True
            )

        subprocess.run(
            ["git", "-C", str(real), "config", "user.email", "real@real.com"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(decoy), "config", "user.email", "decoy@decoy.com"],
            check=True,
            capture_output=True,
        )

        landed = subprocess.run(
            ["git", "-C", str(real), "config", "--get", "user.email"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        assert landed == "real@real.com"
