from __future__ import annotations

import json

from tests.helpers import copy_from_repo, parse_json_output, run_bash, run_cmd


def test_bootstrap_and_hook_install_flow(repo_root, tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    init_script = repo_root / "init-project.sh"
    init_res = run_bash(init_script, cwd=project, args=["Demo", "Python", "active"])
    assert init_res.returncode == 0, init_res.stderr

    assert (project / ".superharness/contract.yaml").exists()
    assert (project / "CLAUDE.md").exists()
    assert (project / "AGENTS.md").exists()

    # Install git hooks into a temp git repo that has the required scripts/hook files.
    for rel in [
        "scripts/check-shell-entrypoints.sh",
        "scripts/check-contract-hygiene.sh",
        "scripts/delegate-to-claude.sh",
        "scripts/delegate-to-codex.sh",
        "scripts/ensure-launchd-inbox-watcher.sh",
        "scripts/inbox-dispatch.sh",
        "scripts/inbox-enqueue.sh",
        "scripts/inbox-normalize.sh",
        "scripts/inbox-recover-stale.sh",
        "scripts/inbox-watch.sh",
        "scripts/install-launchd-inbox-watcher.sh",
        "scripts/install-git-hooks.sh",
        "scripts/uninstall-launchd-inbox-watcher.sh",
        ".githooks/pre-commit",
        "init-project.sh",
        "adapters/claude-code/install.sh",
        "adapters/claude-code/hooks/branch-guard.sh",
        "adapters/claude-code/hooks/ledger-append.sh",
        "adapters/claude-code/hooks/scope-guard.sh",
        "adapters/claude-code/hooks/session-start.sh",
        "identity/core.md",
        "scripts/inbox-yaml.rb",
    ]:
        copy_from_repo(rel, project)

    run_cmd(["git", "init"], cwd=project)
    run_cmd(["git", "config", "user.email", "test@example.com"], cwd=project)
    run_cmd(["git", "config", "user.name", "tester"], cwd=project)
    run_cmd(["git", "add", "."], cwd=project)

    isolated_home = project / "home"
    isolated_home.mkdir()
    install_hooks = run_bash(
        project / "scripts/install-git-hooks.sh",
        cwd=project,
        env={"HOME": str(isolated_home)},
    )
    assert install_hooks.returncode == 0

    hooks_path = run_cmd(["git", "config", "--get", "core.hooksPath"], cwd=project)
    assert hooks_path.stdout.strip() == ".githooks"


def test_policy_enforcement_block_and_warn(repo_root, tmp_path) -> None:
    branch_guard = repo_root / "adapters/claude-code/hooks/branch-guard.sh"
    scope_guard = repo_root / "adapters/claude-code/hooks/scope-guard.sh"

    block_payload = json.dumps({"tool_input": {"command": "git push origin main"}})
    block_res = run_bash(branch_guard, cwd=tmp_path, stdin=block_payload)
    block = parse_json_output(block_res.stdout)
    assert block["decision"] == "block"

    warn_payload = json.dumps({"tool_input": {"file_path": "/etc/passwd"}})
    warn_res = run_bash(scope_guard, cwd=tmp_path, stdin=warn_payload)
    warn = parse_json_output(warn_res.stdout)
    assert warn["decision"] == "warn"
