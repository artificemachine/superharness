from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml, get_task_from_sqlite

import pytest


def _load_monitor_module(repo_root: Path):
    script = repo_root / "src" / "superharness" / "scripts" / "dashboard-ui.py"
    spec = importlib.util.spec_from_file_location("monitor_ui_module", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: monitor-contract",
                "created: 2026-03-09",
                "goal: \"Monitor\"",
                "tasks: []",
            ]
        )
        + "\n"
    )
    (harness / "ledger.md").write_text("Append-only activity log. Never edit previous entries.\n- [2026-03-09T12:00:00Z] monitor test\n")
    (harness / "inbox.yaml").write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale",
                "",
                "- id: sample-item",
                "  to: codex-cli",
                "  task: mcp-docs",
                f"  project: {project}",
                "  status: pending",
                "  priority: 1",
                "  retry_count: 0",
                "  max_retries: 3",
            ]
        )
        + "\n"
    )
    seed_sqlite_from_yaml(project)
    return project


def _start_server(module, repo_root: Path, project: Path):
    module.Handler.project_dir = project
    module.Handler.label = module.project_label(project)
    module.Handler.refresh_seconds = 3
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"
    module.Handler.logdy_port = 8797
    module.Handler.auth_token = f"unit-{uuid.uuid4().hex}"
    module.Handler.logdy_process = None
    try:
        server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    except PermissionError as exc:
        pytest.skip(f"Socket bind not permitted in this environment: {exc}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    return server, thread, base_url


def _request_json(method: str, url: str, payload: dict | None = None, headers: dict[str, str] | None = None):
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _stop_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_status_returns_contract_and_counts(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {
            "loaded": True,
            "state": "running",
            "last_exit_code": "0",
            "run_interval_seconds": 15,
        },
    )
    monkeypatch.setattr(module, "contract_id", lambda path: "monitor-contract")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/status")
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload["contract_id"] == "monitor-contract"
    assert payload["inbox_counts"]["pending"] == 1
    assert payload["watcher_health"]["level"] == "ok"
    assert any("monitor test" in line for line in payload["ledger_tail"])


def test_monitor_action_rejects_missing_token(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(module.Handler, "_action", lambda self, action: (_ for _ in ()).throw(AssertionError("should not run")))

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "dispatch_print_codex"},
            headers={"Origin": base_url, "Content-Type": "application/json"},
        )
    finally:
        _stop_server(server, thread)

    assert status == 403
    assert payload["error"] == "forbidden"


def test_monitor_action_rejects_cross_origin_with_token(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(module.Handler, "_action", lambda self, action: (_ for _ in ()).throw(AssertionError("should not run")))

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "dispatch_print_codex"},
            headers={
                "Origin": "https://evil.example",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 403
    assert payload["error"] == "forbidden"


def test_monitor_action_accepts_same_origin_with_token(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(module.Handler, "_action", lambda self, action, payload=None: ({"exit_code": 0, "stdout": action, "stderr": ""}, 200))

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "dispatch_print_codex"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload["stdout"] == "dispatch_print_codex"


def test_monitor_action_remove_item_calls_inbox_remove(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    captured: dict[str, object] = {}

    def fake_run_cmd(self, args, timeout=30):  # noqa: ANN001, ANN202
        captured["args"] = args
        captured["timeout"] = timeout
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "remove_item:sample-item"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload["stdout"] == "ok"
    args = captured["args"]
    assert isinstance(args, list)
    assert "remove" in args
    assert "--id" in args
    assert "sample-item" in args


@pytest.mark.skipif(sys.platform == "win32", reason="launchctl/os.getuid not available on Windows")
def test_monitor_action_watcher_start_installs_and_kickstarts(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    calls: list[list[str]] = []

    def fake_run_cmd(self, args, timeout=30):  # noqa: ANN001, ANN202
        calls.append(args)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "watcher_start"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload["exit_code"] == 0
    assert len(calls) == 2
    install_call = calls[0]
    kickstart_call = calls[1]
    assert "superharness.commands.watcher_worker" in " ".join(install_call)
    assert "--project" in install_call
    assert str(project) in install_call
    assert "--worker" in install_call
    assert "--interval" in install_call
    assert "15" in install_call
    assert "--launcher-timeout" in install_call
    assert "900" in install_call
    assert kickstart_call[:3] == ["launchctl", "kickstart", "-k"]


@pytest.mark.skipif(sys.platform == "win32", reason="launchctl/os.getuid not available on Windows")
def test_monitor_action_watcher_start_prefers_project_runtime_and_src(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    (project / "src" / "superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "watcher.yaml").write_text(
        "\n".join(
            [
                f'watcher_project: "{project}"',
                'python_executable: "/tmp/project-python"',
                "interval_seconds: 15",
                "launcher_timeout_seconds: 900",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_run_cmd(self, args, timeout=30):  # noqa: ANN001, ANN202
        calls.append(args)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "watcher_start"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload["exit_code"] == 0
    install_call = calls[0]
    assert install_call[0] == "/usr/bin/env"
    assert any(part.startswith("PYTHONPATH=") and str(project / "src") in part for part in install_call)
    assert "/tmp/project-python" in install_call


def test_monitor_main_rejects_non_loopback_host(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    with pytest.raises(SystemExit, match="loopback-only"):
        import sys

        argv = sys.argv
        sys.argv = [
            "dashboard-ui.py",
            "--project",
            str(project),
            "--host",
            "0.0.0.0",
        ]
        try:
            module.main()
        finally:
            sys.argv = argv


# ---------------------------------------------------------------------------
# plan_proposals() and _confirm_plan() — direct import coverage
# ---------------------------------------------------------------------------


def _setup_plan_project(tmp_path: Path) -> Path:
    """Project with one plan_proposed task and a matching handoff."""
    project = tmp_path / "plan_proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "id: plan-contract\n"
        "goal: test plan gate\n"
        "tasks:\n"
        "  - id: feature-x\n"
        "    title: Implement feature X\n"
        "    status: plan_proposed\n"
        "    owner: claude-code\n"
        "    summary: Will add feature X to the engine\n"
    )
    (harness / "handoffs" / "feature-x.yaml").write_text(
        "task: feature-x\n"
        "status: plan_proposed\n"
        "summary: Plan to implement feature X by modifying engine/contract.rb\n"
        "plan_gate:\n"
        "  required: true\n"
        "  confirmed_by_user: false\n"
    )
    return project


def test_plan_proposals_returns_plan_proposed_tasks(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_plan_project(tmp_path)
    harness = project / ".superharness"

    proposals = module.plan_proposals(harness)

    assert len(proposals) == 1
    p = proposals[0]
    assert p["task"] == "feature-x"
    assert p["title"] == "Implement feature X"
    assert p["from"] == "claude-code"
    assert "feature X" in p["summary"]


def test_plan_proposals_returns_empty_when_no_plan_proposed(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)  # has no plan_proposed tasks
    harness = project / ".superharness"

    proposals = module.plan_proposals(harness)

    assert proposals == []


def test_plan_proposals_returns_empty_when_no_contract(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    harness = tmp_path / ".superharness"
    harness.mkdir()

    proposals = module.plan_proposals(harness)

    assert proposals == []


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_confirm_plan_updates_contract_and_handoff(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_plan_project(tmp_path)
    harness = project / ".superharness"

    result = module._confirm_plan(harness, "feature-x")

    assert result["ok"] is True
    assert result["task"] == "feature-x"
    assert "confirmed_at" in result

    # Contract task must now be todo
    import yaml
    doc = yaml.safe_load((harness / "contract.yaml").read_text())
    task = next(t for t in doc["tasks"] if t["id"] == "feature-x")
    assert task["status"] == "todo"
    assert "plan_confirmed_at" in task

    # Handoff must be updated
    hf = harness / "handoffs" / "feature-x.yaml"
    hdata = yaml.safe_load(hf.read_text())
    assert hdata["status"] == "plan_confirmed"
    assert hdata["plan_gate"]["confirmed_by_user"] is True


def test_confirm_plan_returns_error_for_unknown_task(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_plan_project(tmp_path)
    harness = project / ".superharness"

    result = module._confirm_plan(harness, "nonexistent-task")

    assert result["ok"] is False
    assert any("not found" in e for e in result.get("errors", []))


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_confirm_plan_action_via_api(repo_root, tmp_path, monkeypatch) -> None:
    """confirm_plan:<task_id> action via HTTP API updates contract and handoff."""
    module = _load_monitor_module(repo_root)
    project = _setup_plan_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": True, "state": "running", "last_exit_code": "0", "run_interval_seconds": 15},
    )
    monkeypatch.setattr(module, "contract_id", lambda path: "plan-contract")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "confirm_plan:feature-x"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload.get("ok") is True


@pytest.mark.skipif(sys.platform == "win32", reason="launchctl/os.getuid not available on Windows")
def test_monitor_helpers_parse_runtime_and_inbox(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    class _RunResult:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: _RunResult(
            0,
            "state = running\nlast exit code = 0\nrun interval = 15 seconds\n",
        ),
    )
    runtime = module.watcher_runtime("com.example.test")
    assert runtime["loaded"] is True
    assert runtime["state"] == "running"
    assert runtime["last_exit_code"] == "0"
    assert runtime["run_interval_seconds"] == 15

    inbox = project / ".superharness" / "inbox.yaml"
    items = module.inbox_items(inbox)
    assert len(items) == 1
    assert items[0]["id"] == "sample-item"
    assert module.inbox_counts(inbox)["pending"] == 1
    assert module.parse_utc_timestamp("2026-03-12T00:00:00Z") is not None
    assert module.parse_utc_timestamp("invalid") is None


def test_monitor_watcher_health_branches(repo_root) -> None:
    module = _load_monitor_module(repo_root)
    now = "2026-03-12T00:10:00Z"

    not_loaded = module.watcher_health(
        {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
        [],
        now,
    )
    assert not_loaded["level"] == "bad"

    foreground_ok = module.watcher_health(
        {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
        [],
        now,
        heartbeat={"level": "ok", "message": "Heartbeat OK (3s ago)."},
    )
    assert foreground_ok["level"] == "ok"
    assert "foreground" in foreground_ok["message"].lower() or "manual" in foreground_ok["message"].lower()

    idle_ok = module.watcher_health(
        {"loaded": True, "state": "not running", "last_exit_code": "0", "run_interval_seconds": 15},
        [],
        now,
    )
    assert idle_ok["level"] == "ok"

    active_warn = module.watcher_health(
        {"loaded": True, "state": "active", "last_exit_code": "0", "run_interval_seconds": 15},
        [{"status": "stale"}, {"status": "failed"}],
        now,
    )
    assert active_warn["level"] == "warn"

    unknown_state = module.watcher_health(
        {"loaded": True, "state": "throttled", "last_exit_code": "5", "run_interval_seconds": 0},
        [],
        now,
    )
    assert unknown_state["level"] == "warn"

    aging_pending = module.watcher_health(
        {"loaded": True, "state": "running", "last_exit_code": "7", "run_interval_seconds": 0},
        [{"status": "pending", "created_at": "2026-03-12T00:00:00Z"}],
        "2026-03-12T00:20:01Z",
    )
    assert aging_pending["level"] == "warn"
    assert aging_pending["oldest_pending_age_seconds"] > 300


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_config_and_pending_approvals(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    handoff_dir = project / ".superharness" / "handoffs"
    md = project / ".superharness" / "handoffs" / "report.md"
    md.write_text("# Report\n")
    (handoff_dir / "one.yaml").write_text(
        "\n".join(
            [
                "task: t1",
                "status: pending_user_approval",
                "markdown_report: .superharness/handoffs/report.md",
                "approval_gate:",
                "  required: true",
                "  approved_by_user: false",
            ]
        )
        + "\n"
    )

    approvals = module.pending_approvals(handoff_dir)
    assert len(approvals) == 1
    assert approvals[0]["task"] == "t1"
    assert approvals[0]["required"] is True

    cfg = project / ".superharness" / "watcher.yaml"
    cfg.write_text(
        "\n".join(
            [
                f"watcher_project: \"{project}\"",
                "interval_seconds: 20",
                "recover_timeout_minutes: 8",
                "recover_action: retry",
                "launcher_timeout_seconds: 77",
                "target: codex-cli",
                "codex_bypass: true",
            ]
        )
        + "\n"
    )
    parsed = module.watcher_config(project)
    assert parsed["interval_seconds"] == 20
    assert parsed["recover_timeout_minutes"] == 8
    assert parsed["recover_action"] == "retry"
    assert parsed["launcher_timeout_seconds"] == 77
    assert parsed["target"] == "codex-cli"
    assert parsed["codex_bypass"] is True

    assert module.contract_id(project / ".superharness" / "contract.yaml") == "monitor-contract"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_action_retry_and_stop_paths(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    inbox = project / ".superharness" / "inbox.yaml"
    inbox.write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale",
                "",
                "- id: retry-me",
                "  status: stale",
                "  task: t1",
                f"  project: {project}",
                "  to: codex-cli",
                "- id: stop-me",
                "  status: launched",
                "  task: t2",
                f"  project: {project}",
                "  to: codex-cli",
                "  pid: 999999",
                "- id: wrong-retry",
                "  status: done",
                "  task: t3",
                f"  project: {project}",
                "  to: codex-cli",
            ]
        )
        + "\n"
    )

    captured: list[list[str]] = []

    def fake_run_cmd(self, args, timeout=30):  # noqa: ANN001, ANN202
        captured.append(args)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(module.os, "kill", lambda *args, **kwargs: None)

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    h = module.Handler.__new__(module.Handler)
    retry_ok, status_ok = h._action("retry_item:retry-me")
    assert status_ok == 200
    assert retry_ok["stdout"] == "ok"

    retry_missing, status_missing = h._action("retry_item:missing")
    assert status_missing == 404
    assert "item not found" in retry_missing["error"]

    retry_bad, status_bad = h._action("retry_item:wrong-retry")
    assert status_bad == 400
    assert "cannot retry from status" in retry_bad["error"]

    stop_ok, status_stop = h._action("stop_item:stop-me")
    assert status_stop == 200
    assert stop_ok["stdout"] == "ok"

    unsupported, status_unsup = h._action("unsupported")
    assert status_unsup == 400
    assert "unsupported action" in unsupported["error"]
    assert any("set_status" in " ".join(cmd) for cmd in captured)


def test_monitor_watcher_runtime_nonzero_exit(repo_root, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)

    class _RunResult:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: _RunResult(1, ""),
    )
    runtime = module.watcher_runtime("com.example.test")
    assert runtime["loaded"] is False


@pytest.mark.skipif(sys.platform == "win32", reason="launchctl/os.getuid not available on Windows")
def test_monitor_watcher_runtime_unparseable_interval(repo_root, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)

    class _RunResult:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: _RunResult(0, "state = running\nrun interval = notanumber seconds\n"),
    )
    runtime = module.watcher_runtime("com.example.test")
    assert runtime["loaded"] is True
    assert runtime["run_interval_seconds"] == 0


def test_monitor_watcher_runtime_exception(repo_root, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)

    def _raise(*args, **kwargs):
        raise OSError("subprocess failed")

    monkeypatch.setattr(module.subprocess, "run", _raise)
    runtime = module.watcher_runtime("com.example.test")
    assert runtime["loaded"] is False


def test_monitor_watcher_health_stale_and_failed_backlog(repo_root) -> None:
    module = _load_monitor_module(repo_root)
    now = "2026-03-12T00:10:00Z"

    result = module.watcher_health(
        {"loaded": True, "state": "running", "last_exit_code": "0", "run_interval_seconds": 15},
        [{"status": "stale"}, {"status": "failed"}, {"status": "pending"}],
        now,
    )
    assert result["level"] == "warn"
    assert result["stale_count"] == 1
    assert result["failed_count"] == 1


def test_monitor_watcher_health_running_healthy(repo_root) -> None:
    module = _load_monitor_module(repo_root)
    now = "2026-03-12T00:10:00Z"

    result = module.watcher_health(
        {"loaded": True, "state": "running", "last_exit_code": "0", "run_interval_seconds": 15},
        [{"status": "pending"}],
        now,
    )
    assert result["level"] == "ok"
    assert "active" in result["message"]


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_contract_id_reads_yaml(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    cid = module.contract_id(project / ".superharness" / "contract.yaml")
    assert cid == "monitor-contract"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_contract_id_missing_file(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    cid = module.contract_id(tmp_path / "nonexistent" / "contract.yaml")
    assert cid == ""


def test_monitor_html_endpoint(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
    )

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        req = urllib.request.Request(base_url + "/")
        with urllib.request.urlopen(req, timeout=2) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "superharness dashboard" in body
    finally:
        _stop_server(server, thread)


def test_monitor_handoff_md_endpoint(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
    )

    report = project / ".superharness" / "handoffs" / "test-report.md"
    report.write_text("# Test Report\nSome content.\n")

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        req = urllib.request.Request(base_url + "/.superharness/handoffs/test-report.md")
        with urllib.request.urlopen(req, timeout=2) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "Test Report" in body
    finally:
        _stop_server(server, thread)


def test_monitor_handoff_md_not_found(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
    )

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        req = urllib.request.Request(base_url + "/.superharness/handoffs/nonexistent.md")
        try:
            urllib.request.urlopen(req, timeout=2)
            assert False, "Expected 404"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        _stop_server(server, thread)


def test_monitor_handoff_md_path_traversal(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
    )

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        req = urllib.request.Request(base_url + "/.superharness/handoffs/../../contract.yaml")
        try:
            urllib.request.urlopen(req, timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code in (403, 404)
    finally:
        _stop_server(server, thread)


def test_monitor_action_approve_task(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    captured: list[list[str]] = []

    def fake_run_cmd(self, args, timeout=30):
        captured.append(args)
        return {"exit_code": 0, "stdout": "approved", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    h = module.Handler.__new__(module.Handler)
    result, status = h._action("approve_task:my-task")
    assert status == 200
    assert result["stdout"] == "approved"
    args = captured[0]
    assert "approve" in args
    assert "--task" in args
    assert "my-task" in args


def test_monitor_action_approve_task_empty_id(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    h = module.Handler.__new__(module.Handler)
    result, status = h._action("approve_task:")
    assert status == 400
    assert "missing task id" in result["error"]


def test_monitor_action_pause_and_resume_item(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    captured: list[list[str]] = []

    def fake_run_cmd(self, args, timeout=30):
        captured.append(args)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    h = module.Handler.__new__(module.Handler)

    result, status = h._action("pause_item:item-1")
    assert status == 200
    pause_args = captured[0]
    assert "set_status" in pause_args
    assert "--to" in pause_args
    idx = pause_args.index("--to")
    assert pause_args[idx + 1] == "paused"

    result, status = h._action("resume_item:item-1")
    assert status == 200
    resume_args = captured[1]
    assert "set_status" in resume_args
    idx = resume_args.index("--to")
    assert resume_args[idx + 1] == "pending"


def test_monitor_action_dispatch_and_recover(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    captured: list[list[str]] = []

    def fake_run_cmd(self, args, timeout=30):
        captured.append(args)
        return {"exit_code": 0, "stdout": "done", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    h = module.Handler.__new__(module.Handler)

    result, status = h._action("dispatch_print_codex")
    assert status == 200
    assert "inbox-dispatch.sh" in " ".join(captured[-1])
    assert "--to" in captured[-1]
    assert "codex-cli" in captured[-1]

    result, status = h._action("dispatch_print_claude")
    assert status == 200
    assert "claude-code" in captured[-1]

    result, status = h._action("recover_retry")
    assert status == 200
    assert "inbox-recover-stale.sh" in " ".join(captured[-1])

    result, status = h._action("normalize_stale")
    assert status == 200
    assert "inbox-normalize.sh" in " ".join(captured[-1])


def test_monitor_heartbeat_health_missing(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    result = module.heartbeat_health(project)
    assert result["level"] == "warn"
    assert "missing" in result["message"].lower() or "no heartbeat" in result["message"].lower()


def test_monitor_heartbeat_health_stale(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    heartbeat = project / ".superharness" / "watcher.heartbeat"

    import time as _time
    from datetime import datetime, timezone

    stale_time = _time.time() - 600
    stale_ts = datetime.fromtimestamp(stale_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    heartbeat.write_text(stale_ts + "\n")

    result = module.heartbeat_health(project)
    assert result["level"] == "warn"
    assert "stale" in result["message"].lower()


def test_monitor_heartbeat_health_reads_worker_project(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    worker = tmp_path / "worker"
    (worker / ".superharness").mkdir(parents=True)
    (project / ".superharness" / "watcher.yaml").write_text(
        f'watcher_project: "{worker}"\ninterval_seconds: 30\n',
        encoding="utf-8",
    )
    from datetime import datetime, timezone

    fresh_ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (worker / ".superharness" / "watcher.heartbeat").write_text(fresh_ts + "\n", encoding="utf-8")
    (project / ".superharness" / "watcher.heartbeat").write_text("2026-01-01T00:00:00Z\n", encoding="utf-8")

    result = module.heartbeat_health(project)

    assert result["level"] == "ok"
    assert "worker project" in result["message"]
    assert result["age_seconds"] >= 0


def test_monitor_heartbeat_health_ok(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    heartbeat = project / ".superharness" / "watcher.heartbeat"

    from datetime import datetime, timezone

    fresh_ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    heartbeat.write_text(fresh_ts + "\n")

    result = module.heartbeat_health(project)
    assert result["level"] == "ok"
    assert result["age_seconds"] < 10


def test_monitor_status_includes_heartbeat(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {
            "loaded": True,
            "state": "running",
            "last_exit_code": "0",
            "run_interval_seconds": 15,
        },
    )
    monkeypatch.setattr(module, "contract_id", lambda path: "demo")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/status")
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert "heartbeat" in payload
    assert payload["heartbeat"]["level"] in ("ok", "warn")


def test_monitor_status_reports_foreground_when_heartbeat_ok_and_launchd_missing(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
    )
    monkeypatch.setattr(
        module,
        "heartbeat_health",
        lambda project_dir: {"level": "ok", "message": "Heartbeat OK (2s ago).", "age_seconds": 2},
    )
    monkeypatch.setattr(module, "contract_id", lambda path: "demo")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/status")
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload["launchctl_state"] == "foreground"
    assert payload["watcher_health"]["level"] == "ok"
    assert "foreground" in payload["watcher_health"]["message"].lower()


def test_version_sanity_warns_when_dashboard_drifts_from_checkout(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    (project / "src" / "superharness").mkdir(parents=True, exist_ok=True)
    (project / "src" / "superharness" / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    worker = tmp_path / "worker"
    (worker / "src" / "superharness").mkdir(parents=True, exist_ok=True)
    (worker / "src" / "superharness" / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    (project / ".superharness" / "watcher.yaml").write_text(
        f'watcher_project: "{worker}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "_get_installed_version", lambda: "1.34.1")

    sanity = module.version_sanity(project)

    assert sanity["level"] == "warn"
    assert sanity["project_version"] == "9.9.9"
    assert any("dashboard process" in issue for issue in sanity["issues"])


def test_monitor_action_stop_item_not_found(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    h = module.Handler.__new__(module.Handler)
    result, status = h._action("stop_item:nonexistent")
    assert status == 404
    assert "item not found" in result["error"]


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_task_report_contract_summary(repo_root, tmp_path) -> None:
    """task_report returns contract task status and summary."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-report"
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    (harness / "contract.yaml").write_text(
        "id: c1\ntasks:\n"
        "  - id: my-task\n    owner: claude-code\n    status: done\n"
        "    summary: |\n      Implemented feature X with tests.\n"
    )

    result = module.task_report(project, "my-task", "claude-code")
    assert result["contract_status"] == "done"
    assert "feature X" in result["contract_summary"]


def test_task_report_handoff_and_markdown(repo_root, tmp_path) -> None:
    """task_report returns handoff summary and markdown report content."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-report-md"
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True)
    (harness / "contract.yaml").write_text("id: c1\ntasks: []\n")
    (harness / "handoffs" / "2026-03-12-my-task.yaml").write_text(
        "task: my-task\nto: codex-cli\nstatus: done\n"
        "summary: Did the thing.\n"
        "markdown_report: .superharness/handoffs/2026-03-12-my-task.md\n"
    )
    (harness / "handoffs" / "2026-03-12-my-task.md").write_text(
        "# My Task Report\n\nCompleted successfully.\n"
    )

    result = module.task_report(project, "my-task", "codex-cli")
    assert result["handoff_summary"] == "Did the thing."
    assert "Completed successfully" in result["markdown_report"]


def test_task_report_discussion_submission(repo_root, tmp_path) -> None:
    """task_report returns discussion state and agent submission."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-report-disc"
    harness = project / ".superharness"
    disc_dir = harness / "discussions" / "discuss-test-123"
    disc_dir.mkdir(parents=True)
    (harness / "handoffs").mkdir(parents=True)
    (harness / "contract.yaml").write_text("id: c1\ntasks: []\n")
    (disc_dir / "state.yaml").write_text(
        "id: discuss-test-123\ntopic: Review approach\n"
        "status: active\ncurrent_round: 1\nmax_rounds: 3\n"
        "participants:\n  - claude-code\n  - codex-cli\n"
    )
    (disc_dir / "round-1-claude-code.yaml").write_text(
        "discussion_id: discuss-test-123\nround: 1\nagent: claude-code\n"
        "verdict: partial\nposition: Need more testing.\n"
    )

    result = module.task_report(project, "discuss-test-123/round-1", "claude-code")
    assert result["discussion_topic"] == "Review approach"
    assert result["discussion_status"] == "active"
    assert result["discussion_verdict"] == "partial"
    assert "Need more testing" in result["discussion_position"]


def test_task_report_discussion_all_agents(repo_root, tmp_path) -> None:
    """task_report returns all agent positions when no specific agent match."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-report-all"
    harness = project / ".superharness"
    disc_dir = harness / "discussions" / "discuss-all-456"
    disc_dir.mkdir(parents=True)
    (harness / "handoffs").mkdir(parents=True)
    (harness / "contract.yaml").write_text("id: c1\ntasks: []\n")
    (disc_dir / "state.yaml").write_text(
        "id: discuss-all-456\ntopic: Multi agent\n"
        "status: active\ncurrent_round: 1\nmax_rounds: 2\n"
    )
    (disc_dir / "round-1-claude-code.yaml").write_text(
        "agent: claude-code\nverdict: agree\nposition: Looks good.\n"
    )
    (disc_dir / "round-1-codex-cli.yaml").write_text(
        "agent: codex-cli\nverdict: disagree\nposition: Needs rework.\n"
    )

    result = module.task_report(project, "discuss-all-456/round-1", "gemini-cli")
    assert "claude-code" in result.get("discussion_position", "")
    assert "codex-cli" in result.get("discussion_position", "")
    assert "Looks good" in result["discussion_position"]
    assert "Needs rework" in result["discussion_position"]


def test_task_report_missing_data(repo_root, tmp_path) -> None:
    """task_report returns minimal dict when no data exists."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-report-empty"
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    (harness / "contract.yaml").write_text("id: c1\ntasks: []\n")

    result = module.task_report(project, "nonexistent-task", "claude-code")
    assert result["task"] == "nonexistent-task"
    assert result["agent"] == "claude-code"
    assert "contract_summary" not in result
    assert "markdown_report" not in result


# ---------------------------------------------------------------------------
# Port auto-find tests
# ---------------------------------------------------------------------------


def _make_eaddrinuse(errno_code: int = 48) -> OSError:
    import errno as _errno
    exc = OSError(_errno.EADDRINUSE, "Address already in use")
    exc.errno = errno_code
    return exc


def test_monitor_main_auto_finds_free_port(repo_root, tmp_path, monkeypatch) -> None:
    """main() skips occupied ports and starts on the first free one."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    call_log: list[int] = []

    class FakeServer:
        def __init__(self, addr, handler):
            call_log.append(addr[1])
            if addr[1] == 8787:
                raise _make_eaddrinuse()
            self.server_address = addr

        def serve_forever(self):
            return  # immediately "stop" — port selection is already verified via call_log

        def server_close(self):
            pass

    monkeypatch.setattr(module, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(module.webbrowser, "open", lambda url: None)

    import sys
    orig = sys.argv
    sys.argv = ["dashboard-ui.py", "--project", str(project), "--no-open"]
    try:
        module.main()
    except SystemExit as exc:
        assert exc.code == 0 or exc.code is None
    finally:
        sys.argv = orig

    assert 8787 in call_log
    assert 8788 in call_log
    assert call_log.index(8788) == call_log.index(8787) + 1


def test_monitor_main_skips_multiple_occupied_ports(repo_root, tmp_path, monkeypatch) -> None:
    """main() skips several occupied ports before finding a free one."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    busy_ports = {8787, 8788, 8789}
    call_log: list[int] = []

    class FakeServer:
        def __init__(self, addr, handler):
            call_log.append(addr[1])
            if addr[1] in busy_ports:
                raise _make_eaddrinuse()
            self.server_address = addr

        def serve_forever(self):
            return  # immediately "stop" — port selection is already verified via call_log

        def server_close(self):
            pass

    monkeypatch.setattr(module, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(module.webbrowser, "open", lambda url: None)

    import sys
    orig = sys.argv
    sys.argv = ["dashboard-ui.py", "--project", str(project), "--no-open"]
    try:
        module.main()
    except SystemExit as exc:
        assert exc.code == 0 or exc.code is None
    finally:
        sys.argv = orig

    assert call_log[-1] == 8790
    assert set(call_log[:-1]) == busy_ports


def test_monitor_main_exits_when_all_ports_busy(repo_root, tmp_path, monkeypatch) -> None:
    """main() raises SystemExit when no port in the scan range is free."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    class FakeServer:
        def __init__(self, addr, handler):
            raise _make_eaddrinuse()

    monkeypatch.setattr(module, "ThreadingHTTPServer", FakeServer)

    import sys
    orig = sys.argv
    sys.argv = ["dashboard-ui.py", "--project", str(project), "--no-open"]
    try:
        with pytest.raises(SystemExit, match="No free port"):
            module.main()
    finally:
        sys.argv = orig


def test_monitor_main_explicit_port_fails_clearly(repo_root, tmp_path, monkeypatch) -> None:
    """Explicit --port does not fall back; exits with a clear error."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    class FakeServer:
        def __init__(self, addr, handler):
            raise _make_eaddrinuse()

    monkeypatch.setattr(module, "ThreadingHTTPServer", FakeServer)

    import sys
    orig = sys.argv
    sys.argv = ["dashboard-ui.py", "--project", str(project), "--port", "9000", "--no-open"]
    try:
        with pytest.raises(SystemExit, match="9000"):
            module.main()
    finally:
        sys.argv = orig


def test_monitor_main_linux_eaddrinuse(repo_root, tmp_path, monkeypatch) -> None:
    """errno 98 (Linux EADDRINUSE) is also handled by the auto-find logic."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    call_log: list[int] = []

    class FakeServer:
        def __init__(self, addr, handler):
            call_log.append(addr[1])
            if addr[1] == 8787:
                raise _make_eaddrinuse(errno_code=98)
            self.server_address = addr

        def serve_forever(self):
            return  # immediately "stop" — port selection is already verified via call_log

        def server_close(self):
            pass

    monkeypatch.setattr(module, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(module.webbrowser, "open", lambda url: None)

    import sys
    orig = sys.argv
    sys.argv = ["dashboard-ui.py", "--project", str(project), "--no-open"]
    try:
        module.main()
    except SystemExit as exc:
        assert exc.code == 0 or exc.code is None
    finally:
        sys.argv = orig

    assert 8788 in call_log


# ── task lifecycle: _set_task_status ──────────────────────────────────────

def _make_contract(harness: Path, tasks: list[dict]) -> None:
    import yaml
    harness.mkdir(parents=True, exist_ok=True)
    doc = {"id": "test", "status": "active", "tasks": tasks, "decisions": [], "failures": []}
    (harness / "contract.yaml").write_text(yaml.dump(doc))


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_set_task_status_transitions_correctly(repo_root, tmp_path):
    m = _load_monitor_module(repo_root)
    harness = tmp_path / ".superharness"
    _make_contract(harness, [{"id": "t1", "status": "plan_proposed", "title": "T1", "owner": "claude-code"}])
    result = m._set_task_status(harness, "t1", "plan_approved", from_status="plan_proposed")
    assert result["ok"] is True
    import yaml
    doc = yaml.safe_load((harness / "contract.yaml").read_text())
    task = next(t for t in doc["tasks"] if t["id"] == "t1")
    assert task["status"] == "plan_approved"
    assert "plan_approved_at" in task


def test_set_task_status_rejects_wrong_from_status(repo_root, tmp_path):
    m = _load_monitor_module(repo_root)
    harness = tmp_path / ".superharness"
    _make_contract(harness, [{"id": "t1", "status": "in_progress", "title": "T1", "owner": "claude-code"}])
    result = m._set_task_status(harness, "t1", "plan_approved", from_status="plan_proposed")
    assert result["ok"] is False
    assert "in_progress" in result["error"]


def test_set_task_status_missing_task_returns_error(repo_root, tmp_path):
    m = _load_monitor_module(repo_root)
    harness = tmp_path / ".superharness"
    _make_contract(harness, [])
    result = m._set_task_status(harness, "no-such-task", "done")
    assert result["ok"] is False


def test_set_task_status_no_from_status_always_transitions(repo_root, tmp_path):
    m = _load_monitor_module(repo_root)
    harness = tmp_path / ".superharness"
    _make_contract(harness, [{"id": "t1", "status": "in_progress", "title": "T1", "owner": "claude-code"}])
    result = m._set_task_status(harness, "t1", "report_ready")
    assert result["ok"] is True


# ── contract_tasks ────────────────────────────────────────────────────────

@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_contract_tasks_returns_all_tasks(repo_root, tmp_path):
    m = _load_monitor_module(repo_root)
    harness = tmp_path / ".superharness"
    _make_contract(harness, [
        {"id": "a", "status": "todo", "title": "A", "owner": "claude-code"},
        {"id": "b", "status": "plan_proposed", "title": "B", "owner": "codex-cli"},
        {"id": "c", "status": "done", "title": "C", "owner": "claude-code", "verified": True},
    ])
    tasks = m.contract_tasks(harness / "contract.yaml")
    assert len(tasks) == 3
    assert tasks[0] == {"id": "a", "title": "A", "status": "todo", "owner": "claude-code", "review_target": "", "verified": False, "workflow": "", "scheduled_after": "", "due_by": "", "depends_on": []}
    assert tasks[1]["status"] == "plan_proposed"
    assert tasks[2]["verified"] is True


def test_contract_tasks_adds_review_target_for_review_requested(repo_root, tmp_path):
    m = _load_monitor_module(repo_root)
    harness = tmp_path / ".superharness"
    _make_contract(harness, [
        {"id": "r1", "status": "review_requested", "title": "Needs review", "owner": "codex-cli"},
    ])
    tasks = m.contract_tasks(harness / "contract.yaml")
    assert tasks[0]["review_target"] == "claude-code"


def test_contract_tasks_returns_empty_for_missing_file(repo_root, tmp_path):
    m = _load_monitor_module(repo_root)
    assert m.contract_tasks(tmp_path / "nonexistent.yaml") == []


# ── lifecycle phase coverage ──────────────────────────────────────────────

def test_full_lifecycle_status_transitions(repo_root, tmp_path):
    """Walk through all lifecycle phases using _set_task_status."""
    m = _load_monitor_module(repo_root)
    harness = tmp_path / ".superharness"
    _make_contract(harness, [{"id": "task1", "status": "todo", "title": "Full lifecycle", "owner": "claude-code"}])

    transitions = [
        ("todo",          "plan_proposed",    None),
        ("plan_proposed", "plan_approved",    "plan_proposed"),
        ("plan_approved", "in_progress",      "plan_approved"),
        ("in_progress",   "report_ready",     "in_progress"),
        ("report_ready",  "review_requested", "report_ready"),
        ("review_requested", "review_passed", "review_requested"),
        ("review_passed", "done",             None),
    ]
    for from_st, to_st, required_from in transitions:
        r = m._set_task_status(harness, "task1", to_st, from_status=required_from)
        assert r["ok"] is True, f"transition {from_st}→{to_st} failed: {r}"


def test_review_failed_loops_back(repo_root, tmp_path):
    """review_failed → plan_proposed is a valid transition."""
    m = _load_monitor_module(repo_root)
    harness = tmp_path / ".superharness"
    _make_contract(harness, [{"id": "loop-task", "status": "review_failed", "title": "Loop", "owner": "claude-code"}])
    r = m._set_task_status(harness, "loop-task", "plan_proposed", from_status="review_failed")
    assert r["ok"] is True


# ── enqueue_task action tests ─────────────────────────────────────────────


def test_monitor_action_enqueue_task(repo_root, tmp_path, monkeypatch) -> None:
    """enqueue_task:TASK_ID:TARGET calls inbox_enqueue with correct args."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    captured: dict[str, object] = {}

    def fake_run_cmd(self, args, timeout=30):
        captured["args"] = args
        return {"exit_code": 0, "stdout": "Enqueued", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "enqueue_task:mod.0-loader:claude-code"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload["stdout"] == "Enqueued"
    args = captured["args"]
    assert "inbox_enqueue" in " ".join(args)
    assert "--task" in args
    assert "mod.0-loader" in args
    assert "--to" in args
    assert "claude-code" in args
    assert "--priority" in args


def test_monitor_enqueue_with_instructions_saves_file(repo_root, tmp_path, monkeypatch) -> None:
    """enqueue_with_instructions saves instructions file and enqueues task."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    captured: dict[str, object] = {}

    def fake_run_cmd(self, args, timeout=30):
        captured["args"] = args
        return {"exit_code": 0, "stdout": "Enqueued", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={
                "action": "enqueue_task:mod.0-loader:claude-code",
                "instructions": "Use TDD. RED: write 5 failing tests. GREEN: implement loader. REFACTOR: extract helpers.",
            },
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    # Instructions file should be saved
    instructions_file = project / ".superharness" / "handoffs" / "mod.0-loader-instructions.md"
    assert instructions_file.exists()
    content = instructions_file.read_text()
    assert "TDD" in content
    assert "5 failing tests" in content


def test_monitor_action_enqueue_task_invalid_target(repo_root, tmp_path, monkeypatch) -> None:
    """enqueue_task with invalid target returns 400."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "enqueue_task:mod.0-loader:bad-target"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 400
    assert "invalid target" in payload.get("error", "")


def test_monitor_action_enqueue_task_missing_parts(repo_root, tmp_path, monkeypatch) -> None:
    """enqueue_task with missing task_id or target returns 400."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "enqueue_task:mod.0-loader"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 400
    assert "missing" in payload.get("error", "").lower()


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_action_request_review_enqueues_opposite_agent_and_updates_status(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    harness = project / ".superharness"
    _make_contract(
        harness,
        [{"id": "review-me", "status": "report_ready", "title": "Review me", "owner": "codex-cli"}],
    )

    captured: dict[str, object] = {}

    def fake_run_cmd(self, args, timeout=30):  # noqa: ANN001, ANN202
        captured["args"] = args
        return {"exit_code": 0, "stdout": "Enqueued", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)
    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    handler = module.Handler.__new__(module.Handler)
    payload, status = handler._action("request_review:review-me")

    assert status == 200
    assert payload["status"] == "review_requested"
    assert payload["review_target"] == "claude-code"
    assert "Requested review" in payload["stdout"]
    args = captured["args"]
    assert "inbox_enqueue" in " ".join(args)
    assert "--task" in args and "review-me" in args
    assert "--to" in args and "claude-code" in args

    import yaml

    doc = yaml.safe_load((harness / "contract.yaml").read_text())
    task = next(t for t in doc["tasks"] if t["id"] == "review-me")
    assert task["status"] == "review_requested"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_action_request_review_rejects_when_already_enqueued(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    harness = project / ".superharness"
    _make_contract(
        harness,
        [{"id": "review-me", "status": "report_ready", "title": "Review me", "owner": "codex-cli"}],
    )
    (harness / "inbox.yaml").write_text(
        "\n".join(
            [
                "- id: review-item",
                "  to: claude-code",
                "  task: review-me",
                f"  project: {project}",
                "  status: pending",
                "  priority: 1",
            ]
        )
        + "\n"
    )

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    handler = module.Handler.__new__(module.Handler)
    payload, status = handler._action("request_review:review-me")

    assert status == 409
    assert "already enqueued" in payload["error"]


def test_monitor_action_close_without_review_runs_close_command(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    harness = project / ".superharness"
    _make_contract(
        harness,
        [{"id": "close-me", "status": "report_ready", "title": "Close me", "owner": "codex-cli"}],
    )

    captured: dict[str, object] = {}

    def fake_run_cmd(self, args, timeout=30):  # noqa: ANN001, ANN202
        captured["args"] = args
        return {"exit_code": 0, "stdout": "Closed task 'close-me' (actor=owner)", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)
    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    handler = module.Handler.__new__(module.Handler)
    payload, status = handler._action("approve_report:close-me")

    assert status == 200
    assert "Closed task" in payload["stdout"]
    args = captured["args"]
    assert "superharness.commands.close" in " ".join(args)
    assert "--id" in args and "close-me" in args
    assert "--actor" in args and "owner" in args


def test_task_report_endpoint_returns_500_on_crash(repo_root, tmp_path, monkeypatch) -> None:
    """If task_report() raises, endpoint returns 500 JSON instead of dropping connection."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    def exploding_task_report(project_dir, task_id, agent):
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "task_report", exploding_task_report)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "GET",
            base_url + "/api/task-report?task=test-task&agent=claude-code",
        )
    finally:
        _stop_server(server, thread)

    assert status == 500
    assert "boom" in payload.get("error", "")


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_action_enqueue_task_duplicate_blocked(repo_root, tmp_path, monkeypatch) -> None:
    """enqueue_task for a task already in inbox (pending/launched) returns 409."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    # inbox already has an item for task "mcp-docs" (from _setup_project)
    # Add one for mod.0-loader
    inbox_file = project / ".superharness" / "inbox.yaml"
    with open(inbox_file, "a") as f:
        f.write(
            "\n- id: existing-item\n"
            "  to: claude-code\n"
            "  task: mod.0-loader\n"
            f"  project: {project}\n"
            "  status: pending\n"
            "  priority: 2\n"
        )

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "enqueue_task:mod.0-loader:claude-code"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 409
    assert "already" in payload.get("error", "").lower()


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_action_enqueue_task_paused_also_blocked(repo_root, tmp_path, monkeypatch) -> None:
    """enqueue_task for a task with a paused inbox item returns 409."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    inbox_file = project / ".superharness" / "inbox.yaml"
    with open(inbox_file, "a") as f:
        f.write(
            "\n- id: paused-item\n"
            "  to: claude-code\n"
            "  task: mod.0-loader\n"
            f"  project: {project}\n"
            "  status: paused\n"
            "  priority: 2\n"
        )

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "enqueue_task:mod.0-loader:claude-code"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 409
    assert "already" in payload.get("error", "").lower()


def test_monitor_action_enqueue_task_allows_after_done(repo_root, tmp_path, monkeypatch) -> None:
    """enqueue_task allowed if previous inbox item for same task is done."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    inbox_file = project / ".superharness" / "inbox.yaml"
    with open(inbox_file, "a") as f:
        f.write(
            "\n- id: old-item\n"
            "  to: claude-code\n"
            "  task: mod.0-loader\n"
            f"  project: {project}\n"
            "  status: done\n"
            "  priority: 2\n"
        )
    captured: dict[str, object] = {}

    def fake_run_cmd(self, args, timeout=30):
        captured["args"] = args
        return {"exit_code": 0, "stdout": "Enqueued", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "enqueue_task:mod.0-loader:claude-code"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert "mod.0-loader" in captured["args"]


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_action_mark_done(repo_root, tmp_path, monkeypatch) -> None:
    """mark_done transitions task from todo to done."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    harness = project / ".superharness"
    import yaml
    contract = yaml.safe_load((harness / "contract.yaml").read_text()) or {}
    contract["tasks"] = [{"id": "test-task", "status": "todo", "title": "Test", "owner": "claude-code"}]
    (harness / "contract.yaml").write_text(yaml.dump(contract))

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "mark_done:test-task"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload.get("ok") is True
    updated = yaml.safe_load((harness / "contract.yaml").read_text()) or {}
    task = next(t for t in updated["tasks"] if t["id"] == "test-task")
    assert task["status"] == "done"


def test_monitor_action_mark_done_wrong_status(repo_root, tmp_path, monkeypatch) -> None:
    """mark_done on a non-todo task returns error."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    harness = project / ".superharness"
    import yaml
    contract = yaml.safe_load((harness / "contract.yaml").read_text()) or {}
    contract["tasks"] = [{"id": "test-task", "status": "in_progress", "title": "Test", "owner": "claude-code"}]
    (harness / "contract.yaml").write_text(yaml.dump(contract))

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "mark_done:test-task"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 500
    assert payload.get("ok") is not True


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_status_includes_active_inbox_tasks(repo_root, tmp_path, monkeypatch) -> None:
    """Status API includes active_inbox_tasks listing task IDs with active inbox items."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    # Add an active item for mod.0-loader
    inbox_file = project / ".superharness" / "inbox.yaml"
    with open(inbox_file, "a") as f:
        f.write(
            "\n- id: active-item\n"
            "  to: claude-code\n"
            "  task: mod.0-loader\n"
            f"  project: {project}\n"
            "  status: pending\n"
            "  priority: 2\n"
            "\n- id: done-item\n"
            "  to: claude-code\n"
            "  task: mod.1-runner\n"
            f"  project: {project}\n"
            "  status: done\n"
            "  priority: 2\n"
        )

    monkeypatch.setattr(module.Handler, "_run_cmd", lambda self, args, timeout=30: {
        "exit_code": 0, "stdout": "", "stderr": "", "cmd": ""})

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/status")
    finally:
        _stop_server(server, thread)

    assert status == 200
    active = payload.get("active_inbox_tasks", [])
    assert "mod.0-loader" in active
    assert "mod.1-runner" not in active  # done items not active


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_status_includes_done_inbox_tasks(repo_root, tmp_path, monkeypatch) -> None:
    """Status API includes done_inbox_tasks for tasks whose inbox item completed."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    inbox_file = project / ".superharness" / "inbox.yaml"
    with open(inbox_file, "a") as f:
        f.write(
            "\n- id: done-item\n"
            "  to: claude-code\n"
            "  task: mod.0-loader\n"
            f"  project: {project}\n"
            "  status: done\n"
            "  priority: 2\n"
        )

    monkeypatch.setattr(module.Handler, "_run_cmd", lambda self, args, timeout=30: {
        "exit_code": 0, "stdout": "", "stderr": "", "cmd": ""})

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/status")
    finally:
        _stop_server(server, thread)

    assert status == 200
    done = payload.get("done_inbox_tasks", [])
    assert "mod.0-loader" in done
    assert "mod.0-loader" not in payload.get("active_inbox_tasks", [])


def test_task_instructions_includes_plan_section(repo_root, tmp_path) -> None:
    """task_instructions extracts the matching iteration from the plan doc."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-instr"
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    (harness / "contract.yaml").write_text(
        "id: c1\ntasks:\n"
        "- id: mod.3-obsidian\n  title: Obsidian module\n  status: todo\n  owner: claude-code\n"
        "  criteria:\n    - 8 tests pass in test_module_obsidian.py\n"
    )
    docs = project / "docs"
    docs.mkdir()
    (docs / "plan-module-system.md").write_text(
        "# Plan\n\n## Iteration 2: Registry\n\nRegistry stuff\n\n---\n\n"
        "## Iteration 3: Obsidian Module\n\n### RED\n\n"
        "Write 8 tests for vault integration.\n\n### GREEN\n\n"
        "Implement obsidian_write_note action.\n\n---\n\n"
        "## Iteration 4: Auto-schedule\n\nAuto stuff\n"
    )

    result = module.task_instructions(project, "mod.3-obsidian")
    assert "Obsidian module" in result
    assert "Iteration 3" in result
    assert "8 tests" in result
    assert "obsidian_write_note" in result
    assert "Iteration 2" not in result
    assert "Iteration 4" not in result
    assert "TDD plan" in result
    assert "user confirmation" in result


def test_task_instructions_no_plan_still_works(repo_root, tmp_path) -> None:
    """task_instructions returns generic steps when no plan doc exists."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-no-plan"
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    (harness / "contract.yaml").write_text(
        "id: c1\ntasks:\n- id: feat.auto-timeout\n  title: Auto timeout\n  status: todo\n  owner: claude-code\n"
    )

    result = module.task_instructions(project, "feat.auto-timeout")
    assert "Auto timeout" in result
    assert "TDD plan" in result
    assert "user confirmation" in result


def test_task_instructions_includes_prior_failure(repo_root, tmp_path) -> None:
    """task_instructions shows prior failure context when task was previously attempted."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-fail"
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True)
    (harness / "contract.yaml").write_text(
        "id: c1\ntasks:\n- id: mod.3-obsidian\n  title: Obsidian module\n  status: todo\n  owner: claude-code\n"
    )
    (harness / "inbox.yaml").write_text(
        "- id: old-item\n"
        "  task: mod.3-obsidian\n"
        "  to: claude-code\n"
        f"  project: {project}\n"
        "  status: failed\n"
        "  priority: 2\n"
    )
    (harness / "handoffs" / "mod.3-obsidian-report.md").write_text(
        "---\n"
        "task_id: mod.3-obsidian\n"
        "from: claude-code\n"
        "to: owner\n"
        "status: failed\n"
        "---\n\n"
        "# Failed: mod.3-obsidian\n\n"
        "Timed out after 180s. Only completed RED phase — 3 of 8 tests written.\n"
    )

    result = module.task_instructions(project, "mod.3-obsidian")
    assert "Prior Attempt" in result or "prior attempt" in result.lower()
    assert "failed" in result.lower() or "timed out" in result.lower()


def test_task_instructions_api_endpoint(repo_root, tmp_path, monkeypatch) -> None:
    """API endpoint /api/task-instructions returns personalized instructions."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "GET",
            base_url + "/api/task-instructions?task=mcp-docs",
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert "instructions" in payload
    assert "TDD" in payload["instructions"]


def test_task_report_reads_markdown_handoff_with_frontmatter(repo_root, tmp_path) -> None:
    """task_report finds .md handoffs with YAML frontmatter."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-md-handoff"
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True)
    (harness / "contract.yaml").write_text("id: c1\ntasks:\n- id: mod.1-runner\n  status: done\n  title: Runner\n  owner: claude-code\n")
    (harness / "handoffs" / "mod.1-runner-2026-03-20-claude-code.md").write_text(
        "---\n"
        "task_id: mod.1-runner\n"
        "from: claude-code\n"
        "to: next-agent\n"
        "status: done\n"
        "timestamp: 2026-03-20T12:00:00Z\n"
        "---\n\n"
        "# Task: mod.1-runner\n\n"
        "## What Was Done\n\n"
        "Built the module runner with 7 tests.\n"
    )

    result = module.task_report(project, "mod.1-runner", "claude-code")
    assert result["contract_status"] == "done"
    assert result.get("handoff_status") == "done"
    assert "module runner" in result.get("markdown_report", "").lower() or "module runner" in result.get("handoff_summary", "").lower()


def test_task_log_endpoint_returns_log_content(repo_root, tmp_path, monkeypatch) -> None:
    """GET /api/task-log returns log file content for a task."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    log_dir = project / ".superharness" / "launcher-logs"
    log_dir.mkdir(parents=True)
    (log_dir / "mod.5-security-claude-code-20260320T120000Z.log").write_text(
        "Starting task mod.5-security...\nRunning tests...\n5 tests passed.\nDone.\n"
    )

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "GET",
            base_url + "/api/task-log?task=mod.5-security&lines=50",
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert "5 tests passed" in payload["log"]
    assert payload["task"] == "mod.5-security"


def test_task_log_endpoint_no_log(repo_root, tmp_path, monkeypatch) -> None:
    """GET /api/task-log returns placeholder when no log exists."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "GET",
            base_url + "/api/task-log?task=nonexistent",
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert "no log" in payload["log"].lower()


def test_autohealth_loop_exists_and_callable(repo_root, tmp_path, monkeypatch) -> None:
    """autohealth_loop function exists and is callable."""
    module = _load_monitor_module(repo_root)
    assert hasattr(module, "autohealth_loop"), "autohealth_loop function must exist"
    assert callable(module.autohealth_loop)


def test_autohealth_check_returns_health_status(repo_root, tmp_path, monkeypatch) -> None:
    """autohealth_check pings the server and returns True/False."""
    module = _load_monitor_module(repo_root)
    assert hasattr(module, "autohealth_check"), "autohealth_check function must exist"

    # Should return False when nothing is listening
    assert module.autohealth_check(59999) is False


def test_html_contains_enqueue_button_for_todo_tasks(repo_root) -> None:
    """Monitor HTML includes enqueueTask JS function and Enqueue button rendering."""
    module = _load_monitor_module(repo_root)
    html = module.HTML
    assert "enqueueTask" in html
    assert "Enqueue" in html


def test_html_contains_dedicated_left_aligned_task_actions(repo_root) -> None:
    """Task rows render all buttons inside a shared left-aligned actions group."""
    module = _load_monitor_module(repo_root)
    html = module.HTML
    assert ".task-actions" in html
    assert ".task-meta" in html
    assert 'row.className = \'task-row\'' in html
    assert 'class="task-actions"' in html
    assert "actionButtons.join(" in html


def test_html_keeps_view_report_inside_task_actions_group(repo_root) -> None:
    """View Report remains grouped with state-specific task actions."""
    module = _load_monitor_module(repo_root)
    html = module.HTML
    assert "View Report" in html
    assert "actionButtons.push(viewReportBtn);" in html
    assert "actionButtons.push(`<button onclick=\"approvePlan('${tid}')\"" in html
    assert "actionButtons.push(`<button onclick=\"approveReport('${tid}')\"" in html


def test_html_uses_workflow_aware_enqueue_rules(repo_root) -> None:
    """Enqueue affordances must be workflow-aware so the UI matches delegate gating."""
    module = _load_monitor_module(repo_root)
    html = module.HTML
    assert "function inferredWorkflow(task)" in html
    assert "function canEnqueueTask(task)" in html
    assert "workflow === 'implementation'" in html
    assert "['todo', 'plan_approved', 'failed', 'stopped'].includes(st)" in html
    assert "workflow === 'quick' || workflow === 'note'" in html
    assert "const canEnqueue = canEnqueueTask(t);" in html


def test_html_uses_review_first_wording_for_report_ready(repo_root) -> None:
    """Report-ready tasks should offer review first, with explicit close bypass wording."""
    module = _load_monitor_module(repo_root)
    html = module.HTML
    assert "Request Review" in html
    assert "Close Without Review" in html
    assert "Request Opus Review" not in html
    assert "Accept & Close" not in html


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_html_requires_verification_before_close_bypass(repo_root) -> None:
    """Unverified report_ready tasks should not present a misleading close action."""
    module = _load_monitor_module(repo_root)
    html = module.HTML
    assert "Verify First" in html
    assert 'if (t.verified)' in html
    assert 'Run verify before closing' in html


def test_html_shows_reviewer_for_review_requested_rows(repo_root) -> None:
    module = _load_monitor_module(repo_root)
    html = module.HTML
    assert "reviewerInfo" in html
    assert "reviewer ${t.review_target}" in html
    assert "st === 'review_requested' && t.review_target" in html


def test_monitor_bootstraps_into_venv_when_yaml_missing(repo_root) -> None:
    """Repo monitor should have a bootstrap path for missing PyYAML in plain python3."""
    source = (repo_root / "src" / "superharness" / "scripts" / "dashboard-ui.py").read_text()
    assert "def _ensure_python_with_yaml()" in source
    assert 'SUPERHARNESS_MONITOR_REEXEC' in source
    assert '_ensure_python_with_yaml()' in source


# ── feat.monitor-operator-upgrade: board view, review queue, agent health ──


def _setup_board_project(tmp_path: Path) -> Path:
    """Project with tasks across multiple workflow states."""
    import yaml

    project = tmp_path / "board_proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True)
    doc = {
        "id": "board-contract",
        "tasks": [
            {"id": "t-todo", "status": "todo", "title": "Todo task", "owner": "claude-code"},
            {"id": "t-plan-p", "status": "plan_proposed", "title": "Plan proposed", "owner": "claude-code"},
            {"id": "t-plan-a", "status": "plan_approved", "title": "Plan approved", "owner": "codex-cli"},
            {"id": "t-inprog", "status": "in_progress", "title": "In progress", "owner": "claude-code"},
            {"id": "t-rpt", "status": "report_ready", "title": "Report ready", "owner": "codex-cli"},
            {"id": "t-rr", "status": "review_requested", "title": "Review requested", "owner": "claude-code"},
            {"id": "t-rpas", "status": "review_passed", "title": "Review passed", "owner": "codex-cli"},
            {"id": "t-rfail", "status": "review_failed", "title": "Review failed", "owner": "claude-code"},
            {"id": "t-done", "status": "done", "title": "Done task", "owner": "claude-code"},
            {"id": "t-stop", "status": "stopped", "title": "Stopped task", "owner": "codex-cli"},
        ],
    }
    (harness / "contract.yaml").write_text(yaml.dump(doc))
    (harness / "ledger.md").write_text(
        "Append-only activity log. Never edit previous entries.\n"
    )
    (harness / "inbox.yaml").write_text("# Delegation inbox\n")
    return project


def test_board_view_groups_tasks_by_column(repo_root, tmp_path) -> None:
    """board_view() groups tasks into operator board columns."""
    module = _load_monitor_module(repo_root)
    project = _setup_board_project(tmp_path)

    result = module.board_view(project / ".superharness" / "contract.yaml")

    cols = result["columns"]
    assert len(cols["todo"]) == 1
    assert cols["todo"][0]["id"] == "t-todo"
    assert len(cols["plan"]) == 2
    plan_ids = {t["id"] for t in cols["plan"]}
    assert plan_ids == {"t-plan-p", "t-plan-a"}
    assert len(cols["in_progress"]) == 1
    assert cols["in_progress"][0]["id"] == "t-inprog"
    # review column: report_ready + review_requested + review_passed + review_failed
    assert len(cols["review"]) == 4
    assert len(cols["done"]) == 2  # done + stopped


def test_board_view_review_queue_only_review_states(repo_root, tmp_path) -> None:
    """board_view() review_queue contains only review_requested/passed/failed tasks."""
    module = _load_monitor_module(repo_root)
    project = _setup_board_project(tmp_path)

    result = module.board_view(project / ".superharness" / "contract.yaml")

    rq_ids = {t["id"] for t in result["review_queue"]}
    # review_requested, review_passed, review_failed only (not report_ready)
    assert rq_ids == {"t-rr", "t-rpas", "t-rfail"}
    # report_ready should NOT be in review_queue (it awaits operator action)
    assert "t-rpt" not in rq_ids


def test_board_view_totals_match_column_counts(repo_root, tmp_path) -> None:
    """board_view() totals dict matches actual column task counts."""
    module = _load_monitor_module(repo_root)
    project = _setup_board_project(tmp_path)

    result = module.board_view(project / ".superharness" / "contract.yaml")

    for col, tasks in result["columns"].items():
        assert result["totals"][col] == len(tasks), f"totals[{col!r}] mismatch"


def test_board_view_returns_safe_empty_for_missing_contract(repo_root, tmp_path) -> None:
    """board_view() returns safe empty structure when contract.yaml is absent."""
    module = _load_monitor_module(repo_root)
    result = module.board_view(tmp_path / "nonexistent.yaml")
    assert result["review_queue"] == []
    assert all(len(v) == 0 for v in result["columns"].values())


def test_board_api_endpoint_returns_grouped_tasks(repo_root, tmp_path, monkeypatch) -> None:
    """GET /api/board returns columns, review_queue, totals, and now_utc."""
    module = _load_monitor_module(repo_root)
    project = _setup_board_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
    )
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/board")
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert "columns" in payload
    assert "review_queue" in payload
    assert "totals" in payload
    assert "now_utc" in payload
    assert "agent_status" in payload
    assert payload["columns"]["todo"][0]["id"] == "t-todo"
    rq_ids = {t["id"] for t in payload["review_queue"]}
    assert "t-rr" in rq_ids


def test_board_api_includes_agent_status(repo_root, tmp_path, monkeypatch) -> None:
    """GET /api/board includes agent_status from _agent_status_health."""
    module = _load_monitor_module(repo_root)
    project = _setup_board_project(tmp_path)
    monkeypatch.setattr(
        module,
        "_agent_status_health",
        lambda project_dir, **kwargs: {"agents": {"claude-code": {"level": "ok", "message": "healthy"}}},
    )

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/board")
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert "agent_status" in payload
    assert "claude-code" in payload["agent_status"].get("agents", {})
    assert payload["agent_status"]["agents"]["claude-code"]["level"] == "ok"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_status_includes_review_queue_count(repo_root, tmp_path, monkeypatch) -> None:
    """/api/status includes review_queue_count for operator at-a-glance visibility."""
    module = _load_monitor_module(repo_root)
    project = _setup_board_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
    )
    monkeypatch.setattr(module, "contract_id", lambda path: "board-contract")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/status")
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert "review_queue_count" in payload
    # 3 review tasks: review_requested + review_passed + review_failed
    assert payload["review_queue_count"] == 3


def test_board_view_task_fields_are_complete(repo_root, tmp_path) -> None:
    """board_view() task entries include id, title, status, owner, verified, blocked_by."""
    module = _load_monitor_module(repo_root)
    project = _setup_board_project(tmp_path)

    result = module.board_view(project / ".superharness" / "contract.yaml")

    task = result["columns"]["todo"][0]
    for field in ("id", "title", "status", "owner", "verified", "blocked_by"):
        assert field in task, f"missing field: {field!r}"
    assert task["id"] == "t-todo"
    assert task["status"] == "todo"
    assert task["owner"] == "claude-code"
    assert task["verified"] is False
    assert task["blocked_by"] == []


# ── feat.monitor-operator-upgrade tests ──────────────────────────────────────

def _setup_project_with_tasks(tmp_path: Path) -> Path:
    """Create a project with contract tasks spanning multiple workflow states."""
    project = _setup_project(tmp_path)
    harness = project / ".superharness"
    (harness / "contract.yaml").write_text(
        "id: board-contract\n"
        "created: 2026-04-05\n"
        "goal: \"Board test\"\n"
        "tasks:\n"
        "- id: task.todo\n"
        "  title: A todo task\n"
        "  owner: claude-code\n"
        "  status: todo\n"
        "- id: task.plan-proposed\n"
        "  title: A plan proposed task\n"
        "  owner: claude-code\n"
        "  status: plan_proposed\n"
        "- id: task.plan-approved\n"
        "  title: A plan approved task\n"
        "  owner: claude-code\n"
        "  status: plan_approved\n"
        "- id: task.in-progress\n"
        "  title: An active task\n"
        "  owner: codex-cli\n"
        "  status: in_progress\n"
        "- id: task.report-ready\n"
        "  title: A report ready task\n"
        "  owner: claude-code\n"
        "  status: report_ready\n"
        "  verified: false\n"
        "- id: task.review-requested\n"
        "  title: A review requested task\n"
        "  owner: codex-cli\n"
        "  status: review_requested\n"
        "- id: task.review-passed\n"
        "  title: A review passed task\n"
        "  owner: claude-code\n"
        "  status: review_passed\n"
        "- id: task.review-failed\n"
        "  title: A review failed task\n"
        "  owner: codex-cli\n"
        "  status: review_failed\n"
        "- id: task.done\n"
        "  title: A done task\n"
        "  owner: claude-code\n"
        "  status: done\n"
        "- id: task.stopped\n"
        "  title: A stopped task\n"
        "  owner: claude-code\n"
        "  status: stopped\n"
    )
    return project


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_board_tasks_groups_by_column(repo_root) -> None:
    """board_tasks() groups contract tasks into board columns."""
    module = _load_monitor_module(repo_root)
    import tempfile, yaml
    with tempfile.TemporaryDirectory() as tmp:
        contract = Path(tmp) / "contract.yaml"
        contract.write_text(
            "id: test\n"
            "tasks:\n"
            "- {id: t1, title: T1, owner: a, status: todo}\n"
            "- {id: t2, title: T2, owner: a, status: plan_proposed}\n"
            "- {id: t3, title: T3, owner: a, status: plan_approved}\n"
            "- {id: t4, title: T4, owner: a, status: in_progress}\n"
            "- {id: t5, title: T5, owner: a, status: report_ready}\n"
            "- {id: t6, title: T6, owner: a, status: review_requested}\n"
            "- {id: t7, title: T7, owner: a, status: review_passed}\n"
            "- {id: t8, title: T8, owner: a, status: done}\n"
            "- {id: t9, title: T9, owner: a, status: stopped}\n"
        )
        board = module.board_tasks(contract)

    assert "todo" in board
    assert "plan" in board
    assert "active" in board
    assert "review" in board
    assert "done" in board
    assert "stopped" in board

    todo_ids = [t["id"] for t in board["todo"]]
    assert "t1" in todo_ids

    plan_ids = [t["id"] for t in board["plan"]]
    assert "t2" in plan_ids
    assert "t3" in plan_ids

    active_ids = [t["id"] for t in board["active"]]
    assert "t4" in active_ids

    review_ids = [t["id"] for t in board["review"]]
    assert "t5" in review_ids
    assert "t6" in review_ids
    assert "t7" in review_ids

    done_ids = [t["id"] for t in board["done"]]
    assert "t8" in done_ids

    stopped_ids = [t["id"] for t in board["stopped"]]
    assert "t9" in stopped_ids


def test_board_tasks_missing_contract(repo_root, tmp_path) -> None:
    """board_tasks() returns empty dict for missing contract."""
    module = _load_monitor_module(repo_root)
    result = module.board_tasks(tmp_path / "nonexistent.yaml")
    assert result == {}


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_review_queue_returns_review_state_tasks(repo_root) -> None:
    """review_queue() returns tasks in review states ordered by urgency."""
    module = _load_monitor_module(repo_root)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        contract = Path(tmp) / "contract.yaml"
        contract.write_text(
            "id: test\n"
            "tasks:\n"
            "- {id: t1, title: T1, owner: claude-code, status: todo}\n"
            "- {id: t2, title: T2, owner: claude-code, status: report_ready, verified: false}\n"
            "- {id: t3, title: T3, owner: codex-cli, status: review_requested}\n"
            "- {id: t4, title: T4, owner: claude-code, status: review_passed}\n"
            "- {id: t5, title: T5, owner: codex-cli, status: review_failed}\n"
            "- {id: t6, title: T6, owner: claude-code, status: done}\n"
        )
        queue = module.review_queue(contract)

    review_ids = [t["id"] for t in queue]
    # Only review-state tasks
    assert "t1" not in review_ids
    assert "t6" not in review_ids
    assert "t2" in review_ids
    assert "t3" in review_ids
    assert "t4" in review_ids
    assert "t5" in review_ids
    # review_failed should come first (highest urgency)
    assert queue[0]["id"] == "t5"
    # Each item has review_target
    for item in queue:
        assert "review_target" in item


def test_review_queue_empty_for_no_review_tasks(repo_root) -> None:
    """review_queue() returns empty list when no tasks are in review states."""
    module = _load_monitor_module(repo_root)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        contract = Path(tmp) / "contract.yaml"
        contract.write_text(
            "id: test\n"
            "tasks:\n"
            "- {id: t1, title: T1, owner: a, status: todo}\n"
            "- {id: t2, title: T2, owner: a, status: done}\n"
        )
        result = module.review_queue(contract)
    assert result == []


def test_budget_signals_returns_empty_when_no_agents(repo_root, tmp_path) -> None:
    """budget_signals() returns empty agents dict when no agent status files exist."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    result = module.budget_signals(project)
    assert "agents" in result
    assert isinstance(result["agents"], dict)


def test_budget_signals_reads_agent_status_files(repo_root, tmp_path) -> None:
    """budget_signals() reads agent budget data from .superharness/agents/*.status.yaml."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    agents_dir = project / ".superharness" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    # Write a mock agent status file with budget
    (agents_dir / "claude-code.status.yaml").write_text(
        "schema_version: '1'\n"
        "runtime: claude-code\n"
        "updated_at: '2026-04-05T12:00:00Z'\n"
        "liveness: active\n"
        "budget:\n"
        "  model: claude-opus-4-5\n"
        "  input_tokens: 5000\n"
        "  output_tokens: 1000\n"
        "  cost_usd: 0.045\n"
        "  max_budget_usd: 1.0\n"
    )
    result = module.budget_signals(project)
    assert "agents" in result
    # Should have claude-code budget data
    assert "claude-code" in result["agents"] or result.get("available") is False  # fallback ok


def test_monitor_board_endpoint_exists(repo_root, tmp_path, monkeypatch) -> None:
    """GET /api/board returns 200 with board, review_queue, agent_health, budget fields."""
    module = _load_monitor_module(repo_root)
    project = _setup_project_with_tasks(tmp_path)
    monkeypatch.setattr(module, "watcher_runtime", lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0})
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/board")
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert "board" in payload
    assert "review_queue" in payload
    assert "agent_health" in payload
    assert "budget" in payload
    assert "now_utc" in payload


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_board_endpoint_groups_tasks_correctly(repo_root, tmp_path, monkeypatch) -> None:
    """GET /api/board groups tasks into correct columns."""
    module = _load_monitor_module(repo_root)
    project = _setup_project_with_tasks(tmp_path)
    monkeypatch.setattr(module, "watcher_runtime", lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0})
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/board")
    finally:
        _stop_server(server, thread)

    board = payload["board"]
    todo_ids = [t["id"] for t in board.get("todo", [])]
    plan_ids = [t["id"] for t in board.get("plan", [])]
    active_ids = [t["id"] for t in board.get("active", [])]
    review_ids = [t["id"] for t in board.get("review", [])]

    assert "task.todo" in todo_ids
    assert "task.plan-proposed" in plan_ids
    assert "task.plan-approved" in plan_ids
    assert "task.in-progress" in active_ids
    assert "task.report-ready" in review_ids
    assert "task.review-requested" in review_ids
    assert "task.review-passed" in review_ids


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_board_endpoint_review_queue_populated(repo_root, tmp_path, monkeypatch) -> None:
    """GET /api/board includes review queue with tasks in review states."""
    module = _load_monitor_module(repo_root)
    project = _setup_project_with_tasks(tmp_path)
    monkeypatch.setattr(module, "watcher_runtime", lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0})
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/board")
    finally:
        _stop_server(server, thread)

    rq = payload["review_queue"]
    rq_ids = [t["id"] for t in rq]
    assert "task.report-ready" in rq_ids
    assert "task.review-requested" in rq_ids
    assert "task.review-passed" in rq_ids
    assert "task.review-failed" in rq_ids
    # Non-review tasks should NOT be in queue
    assert "task.todo" not in rq_ids
    assert "task.done" not in rq_ids


def test_monitor_review_queue_endpoint_exists(repo_root, tmp_path, monkeypatch) -> None:
    """GET /api/review-queue returns 200 with queue field."""
    module = _load_monitor_module(repo_root)
    project = _setup_project_with_tasks(tmp_path)
    monkeypatch.setattr(module, "watcher_runtime", lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0})
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/review-queue")
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert "queue" in payload
    assert "now_utc" in payload


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_review_queue_endpoint_returns_review_tasks(repo_root, tmp_path, monkeypatch) -> None:
    """GET /api/review-queue returns only review-state tasks."""
    module = _load_monitor_module(repo_root)
    project = _setup_project_with_tasks(tmp_path)
    monkeypatch.setattr(module, "watcher_runtime", lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0})
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/review-queue")
    finally:
        _stop_server(server, thread)

    queue = payload["queue"]
    queue_ids = [t["id"] for t in queue]
    assert "task.report-ready" in queue_ids
    assert "task.review-requested" in queue_ids
    assert "task.todo" not in queue_ids
    assert "task.done" not in queue_ids
    # review_failed should be first (highest urgency)
    assert queue[0]["id"] == "task.review-failed"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_monitor_status_includes_review_queue_and_board(repo_root, tmp_path, monkeypatch) -> None:
    """GET /api/status includes review_queue and board_columns for operator use."""
    module = _load_monitor_module(repo_root)
    project = _setup_project_with_tasks(tmp_path)
    monkeypatch.setattr(module, "watcher_runtime", lambda label: {"loaded": True, "state": "running", "last_exit_code": "0", "run_interval_seconds": 15})
    monkeypatch.setattr(module, "contract_id", lambda path: "board-contract")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/status")
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert "review_queue" in payload
    assert "board_columns" in payload
    # review queue should contain the review-state tasks
    review_ids = [t["id"] for t in payload["review_queue"]]
    assert "task.report-ready" in review_ids
    # board_columns should have column keys
    board = payload["board_columns"]
    assert "todo" in board or "review" in board


def test_monitor_html_contains_board_and_review_queue_elements(repo_root, tmp_path, monkeypatch) -> None:
    """HTML page contains board view and review queue DOM elements."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        import urllib.request
        with urllib.request.urlopen(base_url + "/", timeout=2) as resp:
            html = resp.read().decode("utf-8")
    finally:
        _stop_server(server, thread)

    # Board view element
    assert "boardColumns" in html or "boardView" in html or "board-col" in html
    # Review queue element
    assert "reviewQueueList" in html or "reviewQueueCard" in html or "review queue" in html.lower()
    # Agent health element
    assert "agentHealthList" in html or "agentHealthCard" in html or "agent health" in html.lower()


# ── propose_plan: author plan inline from dashboard ──────────────────────────

def _setup_project_with_todo_task(tmp_path: Path) -> Path:
    """Project with a single todo + implementation task."""
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "id: test-contract\n"
        "created: 2026-04-15\n"
        "goal: Test\n"
        "tasks:\n"
        "  - id: feat.one\n"
        "    title: One\n"
        "    owner: claude-code\n"
        "    status: todo\n"
        "    workflow: implementation\n"
    )
    return project


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_propose_plan_transitions_status_and_writes_handoff(repo_root, tmp_path):
    """_propose_plan_handoff transitions todo->plan_proposed and writes a handoff YAML."""
    module = _load_monitor_module(repo_root)
    project = _setup_project_with_todo_task(tmp_path)
    harness = project / ".superharness"

    result = module._propose_plan_handoff(
        harness,
        "feat.one",
        plan_summary="Implement thing",
        tdd_red="write failing test",
        tdd_green="pass it",
        tdd_refactor="cleanup",
        risks="none",
    )

    assert result["ok"] is True, result
    assert result["status"] == "plan_proposed"

    # Contract status updated
    import yaml
    doc = yaml.safe_load((harness / "contract.yaml").read_text())
    assert doc["tasks"][0]["status"] == "plan_proposed"
    assert doc["tasks"][0]["plan_proposed_at"]

    # Handoff file exists and contains TDD block
    handoffs = list((harness / "handoffs").glob("feat.one-plan-*.yaml"))
    assert len(handoffs) == 1
    ho = yaml.safe_load(handoffs[0].read_text())
    assert ho["task"] == "feat.one"
    assert ho["phase"] == "plan"
    assert ho["status"] == "plan_proposed"
    assert ho["tdd"]["red"] == "write failing test"
    assert ho["tdd"]["green"] == "pass it"
    assert ho["tdd"]["refactor"] == "cleanup"
    assert ho["risks"] == "none"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_propose_plan_rejects_non_todo_task(repo_root, tmp_path):
    """Cannot propose a plan on a task that is not in todo status."""
    module = _load_monitor_module(repo_root)
    project = _setup_project_with_todo_task(tmp_path)
    harness = project / ".superharness"

    # Move task to plan_approved
    module._set_task_status(harness, "feat.one", "plan_approved")

    result = module._propose_plan_handoff(
        harness, "feat.one",
        plan_summary="x", tdd_red="x", tdd_green="x", tdd_refactor="x",
    )
    assert result["ok"] is False
    assert "expected 'todo'" in result["error"]

    # No handoff written
    assert not list((harness / "handoffs").glob("feat.one-plan-*.yaml"))


def test_propose_plan_defaults_empty_tdd_fields_to_placeholder(repo_root, tmp_path):
    """Blank fields become '(... pending)' placeholders so YAML stays valid."""
    module = _load_monitor_module(repo_root)
    project = _setup_project_with_todo_task(tmp_path)
    harness = project / ".superharness"

    result = module._propose_plan_handoff(
        harness, "feat.one",
        plan_summary="", tdd_red="", tdd_green="", tdd_refactor="",
    )
    assert result["ok"] is True

    import yaml
    handoffs = list((harness / "handoffs").glob("feat.one-plan-*.yaml"))
    ho = yaml.safe_load(handoffs[0].read_text())
    assert "pending" in ho["tdd"]["red"]
    assert "pending" in ho["tdd"]["green"]
    assert "pending" in ho["tdd"]["refactor"]
    assert "risks" not in ho  # empty risks omitted


def test_propose_plan_missing_task_returns_error(repo_root, tmp_path):
    module = _load_monitor_module(repo_root)
    project = _setup_project_with_todo_task(tmp_path)
    harness = project / ".superharness"

    result = module._propose_plan_handoff(
        harness, "does.not.exist",
        plan_summary="x", tdd_red="x", tdd_green="x", tdd_refactor="x",
    )
    assert result["ok"] is False
    assert "not found" in result["error"]
