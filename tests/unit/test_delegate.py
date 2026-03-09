from __future__ import annotations

from pathlib import Path

from tests.helpers import run_bash


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: test-contract",
                "tasks:",
                "  - id: mcp-docs",
                "    owner: codex-cli",
                "    status: todo",
                f'    project_path: "{project}"',
            ]
        )
        + "\n"
    )
    return project


def test_delegate_print_only_does_not_require_target_cli(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    script = repo_root / "cli" / "delegate.sh"

    # Use a minimal PATH that does not include user-installed codex/claude CLIs.
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--to", "codex-cli", "--project", str(project), "--task", "mcp-docs", "--print-only"],
        env={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stderr
    assert "Generated prompt:" in result.stdout
    assert "execute task mcp-docs" in result.stdout
