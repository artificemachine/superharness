from __future__ import annotations

from tests.helpers import run_bash

def test_recover_marks_old_launched_items_stale(repo_root, tmp_path) -> None:
    project = tmp_path / "proj-recover"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    (harness / "inbox.yaml").write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale",
                "",
                "- id: stale-item",
                "  to: codex-cli",
                "  task: demo",
                f"  project: {project}",
                "  status: launched",
                "  launched_at: 2026-01-01T00:00:00Z",
                "  priority: 1",
                "  retry_count: 1",
                "  max_retries: 3",
            ]
        )
        + "\n"
    )

    script = repo_root / "scripts" / "inbox-recover-stale.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project), "--timeout-minutes", "20", "--action", "stale"],
    )

    assert result.returncode == 0, result.stderr
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "id: stale-item" in inbox_text
    assert "  status: stale" in inbox_text
    assert "  stale_reason: stale_timeout" in inbox_text
    assert "  launched_at:" not in inbox_text
