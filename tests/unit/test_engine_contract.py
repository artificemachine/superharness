from __future__ import annotations

from pathlib import Path

from tests.helpers import run_cmd


def _contract_file(tmp_path: Path) -> Path:
    f = tmp_path / "contract.yaml"
    f.write_text(
        "id: test-contract-123\n"
        "tasks:\n"
        "  - id: task-a\n"
        "    owner: claude-code\n"
        "    status: todo\n"
        '    project_path: "/some/path"\n'
        "    deadline_minutes: 45\n"
        "  - id: task-b\n"
        "    owner: codex-cli\n"
        "    status: done\n"
        '    project_path: "/other/path"\n'
    )
    return f


def _run_contract(repo_root: Path, cmd: str, args: list[str]) -> object:
    return run_cmd(
        ["ruby", str(repo_root / "engine" / "contract.rb"), cmd] + args,
        cwd=repo_root,
    )


def test_task_exists_true(repo_root, tmp_path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract(repo_root, "task_exists", ["--file", str(f), "--task", "task-a"])
    assert r.returncode == 0
    assert r.stdout.strip() == "true"


def test_task_exists_false(repo_root, tmp_path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract(repo_root, "task_exists", ["--file", str(f), "--task", "nonexistent"])
    assert r.returncode == 0
    assert r.stdout.strip() == "false"


def test_task_exists_empty_contract(repo_root, tmp_path) -> None:
    f = tmp_path / "empty.yaml"
    f.write_text("id: empty\n")
    r = _run_contract(repo_root, "task_exists", ["--file", str(f), "--task", "anything"])
    assert r.returncode == 0
    assert r.stdout.strip() == "false"


def test_task_owner(repo_root, tmp_path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract(repo_root, "task_owner", ["--file", str(f), "--task", "task-a"])
    assert r.returncode == 0
    assert r.stdout.strip() == "claude-code"


def test_task_owner_missing_task(repo_root, tmp_path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract(repo_root, "task_owner", ["--file", str(f), "--task", "nope"])
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_task_status(repo_root, tmp_path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract(repo_root, "task_status", ["--file", str(f), "--task", "task-b"])
    assert r.returncode == 0
    assert r.stdout.strip() == "done"


def test_task_project_path(repo_root, tmp_path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract(repo_root, "task_project_path", ["--file", str(f), "--task", "task-a"])
    assert r.returncode == 0
    assert r.stdout.strip() == "/some/path"


def test_contract_id(repo_root, tmp_path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract(repo_root, "contract_id", ["--file", str(f)])
    assert r.returncode == 0
    assert r.stdout.strip() == "test-contract-123"


def test_task_deadline_minutes(repo_root, tmp_path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract(repo_root, "task_deadline_minutes", ["--file", str(f), "--task", "task-a"])
    assert r.returncode == 0
    assert r.stdout.strip() == "45"


def test_task_deadline_minutes_missing(repo_root, tmp_path) -> None:
    f = _contract_file(tmp_path)
    r = _run_contract(repo_root, "task_deadline_minutes", ["--file", str(f), "--task", "task-b"])
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_latest_handoff_task(repo_root, tmp_path) -> None:
    handoff_dir = tmp_path / "handoffs"
    handoff_dir.mkdir()
    (handoff_dir / "h1.yaml").write_text("task: task-a\nto: claude-code\n")
    (handoff_dir / "h2.yaml").write_text("task: task-b\nto: codex-cli\n")

    r = _run_contract(repo_root, "latest_handoff_task", ["--dir", str(handoff_dir), "--to", "codex-cli"])
    assert r.returncode == 0
    assert "task-b" in r.stdout


def test_latest_handoff_task_no_match(repo_root, tmp_path) -> None:
    handoff_dir = tmp_path / "handoffs"
    handoff_dir.mkdir()
    (handoff_dir / "h1.yaml").write_text("task: task-a\nto: claude-code\n")

    r = _run_contract(repo_root, "latest_handoff_task", ["--dir", str(handoff_dir), "--to", "codex-cli"])
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_missing_required_args(repo_root) -> None:
    r = _run_contract(repo_root, "task_exists", [])
    assert r.returncode != 0
    assert "required" in r.stderr.lower()


def test_unknown_command(repo_root) -> None:
    r = _run_contract(repo_root, "bogus_command", [])
    assert r.returncode != 0
    assert "Usage:" in r.stderr


def test_nonexistent_file(repo_root, tmp_path) -> None:
    r = _run_contract(repo_root, "task_exists", ["--file", str(tmp_path / "nope.yaml"), "--task", "x"])
    assert r.returncode == 0
    assert r.stdout.strip() == "false"


def test_invalid_tasks_shape_fails(repo_root, tmp_path) -> None:
    f = tmp_path / "bad-shape.yaml"
    f.write_text("id: bad\n" 'tasks: "not-a-sequence"\n')
    r = _run_contract(repo_root, "task_exists", ["--file", str(f), "--task", "x"])
    assert r.returncode != 0
    assert "tasks must be a sequence" in r.stderr
