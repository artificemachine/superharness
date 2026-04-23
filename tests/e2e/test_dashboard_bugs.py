from __future__ import annotations

import importlib.util
import json
import threading
import urllib.request
import uuid
from pathlib import Path

import pytest
import yaml

_TEST_AUTH_TOKEN = "test-token"  # noqa: S105 shipguard:ignore test fixture, not a real credential


def _load_monitor_module(repo_root: Path):
    script = repo_root / "src" / "superharness" / "scripts" / "dashboard-ui.py"
    spec = importlib.util.spec_from_file_location("monitor_ui_module", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup_test_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    
    contract = {
        "id": "e2e-contract",
        "created": "2026-04-22",
        "goal": "Test Dashboard Bugs",
        "tasks": [
            {
                "id": "task-1",
                "title": "Task 1",
                "status": "plan_approved",
                "owner": "claude-code",
                "project_path": str(project)
            },
            {
                "id": "task-archived",
                "title": "Archived Task",
                "status": "archived",
                "owner": "codex-cli",
                "project_path": str(project)
            }
        ]
    }
    (harness / "contract.yaml").write_text(yaml.dump(contract))
    (harness / "inbox.yaml").write_text("[]\n")
    (harness / "ledger.md").write_text("ledger")
    return project


def _start_server(module, repo_root: Path, project: Path):
    module.Handler.project_dir = project
    module.Handler.label = "test-label"
    module.Handler.refresh_seconds = 3
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"
    module.Handler.logdy_port = 8798
    module.Handler.auth_token = _TEST_AUTH_TOKEN
    module.Handler.logdy_process = None
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    return server, thread, base_url


def _request_json(method: str, url: str, payload: dict | None = None, base_url: str = "", token: str = _TEST_AUTH_TOKEN):
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    
    headers = {
        "Origin": base_url,
        "Referer": base_url + "/",
        "Content-Type": "application/json",
        "X-Superharness-Token": token
    }
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"DEBUG: HTTP Error {e.code}: {e.read().decode('utf-8')}")
        raise


def test_e2e_owner_swap_affects_modal_initialization(repo_root, tmp_path):
    """E2E: Changing owner via API should result in correct owner in task-instructions (modal init)."""
    module = _load_monitor_module(repo_root)
    project = _setup_test_project(tmp_path)
    server, thread, base_url = _start_server(module, repo_root, project)

    try:
        # 1. Verify initial owner in task-instructions
        status, data = _request_json("GET", f"{base_url}/api/task-instructions?task=task-1", base_url=base_url)
        assert status == 200
        assert data["task_meta"]["owner"] == "claude-code"

        # 2. Change owner via dashboard action API
        # set_owner:task-1:gemini-cli
        status, data = _request_json("POST", f"{base_url}/api/action", payload={"action": "set_owner:task-1:gemini-cli"}, base_url=base_url)
        assert status == 200
        assert data["ok"] is True

        # 3. Verify owner is updated in the status API (main task list)
        status, data = _request_json("GET", f"{base_url}/api/status", base_url=base_url)
        assert status == 200
        t1_status = next(t for t in data["contract_tasks"] if t["id"] == "task-1")
        assert t1_status["owner"] == "gemini-cli"

        # 4. Verify owner is updated in the instructions API (modal initialization)
        status, data = _request_json("GET", f"{base_url}/api/task-instructions?task=task-1", base_url=base_url)
        assert status == 200
        assert data["task_meta"]["owner"] == "gemini-cli"
        
        # 5. Verify the physical contract file on disk was updated
        contract = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
        t1_disk = next(t for t in contract["tasks"] if t["id"] == "task-1")
        assert t1_disk["owner"] == "gemini-cli"

    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_e2e_archived_tasks_correctly_flagged(repo_root, tmp_path):
    """E2E: Verify that archived tasks are correctly identified in the status API."""
    module = _load_monitor_module(repo_root)
    project = _setup_test_project(tmp_path)
    server, thread, base_url = _start_server(module, repo_root, project)

    try:
        status, data = _request_json("GET", f"{base_url}/api/status", base_url=base_url)
        assert status == 200
        tasks = data["contract_tasks"]
        archived = next(t for t in tasks if t["id"] == "task-archived")
        assert archived["status"] == "archived"

    finally:
        server.shutdown()
        server.server_close()
        thread.join()

def test_e2e_archived_dependency_does_not_block(repo_root, tmp_path):
    """E2E: Verify that archived tasks satisfy dependencies (unblocking dependent tasks)."""
    module = _load_monitor_module(repo_root)
    project = _setup_test_project(tmp_path)
    
    # Update contract: task-1 depends on task-archived (which is archived)
    harness = project / ".superharness"
    contract = yaml.safe_load((harness / "contract.yaml").read_text())
    t1 = next(t for t in contract["tasks"] if t["id"] == "task-1")
    t1["blocked_by"] = ["task-archived"]
    (harness / "contract.yaml").write_text(yaml.dump(contract))
    
    server, thread, base_url = _start_server(module, repo_root, project)

    try:
        status, data = _request_json("GET", f"{base_url}/api/status", base_url=base_url)
        assert status == 200
        
        # In the API, depends_on should show the dependency
        tasks = data["contract_tasks"]
        t1_api = next(t for t in tasks if t["id"] == "task-1")
        assert "task-archived" in t1_api["depends_on"]
        
        # Verify that an enqueue attempt for task-1 succeeds (it is NOT blocked)
        status, data = _request_json("POST", f"{base_url}/api/action", 
                                    payload={"action": "enqueue_task:task-1:claude-code"}, 
                                    base_url=base_url)
        assert status == 200
        if data.get("exit_code") != 0:
            print(f"DEBUG action cmd: {data.get('cmd')}")
            print(f"DEBUG action stderr: {data.get('stderr')}")
        assert data["exit_code"] == 0

    finally:
        server.shutdown()
        server.server_close()
        thread.join()

def test_e2e_gemini_cli_enqueuing_supported(repo_root, tmp_path):
    """E2E: Verify that enqueuing to gemini-cli is supported by the API and command."""
    module = _load_monitor_module(repo_root)
    project = _setup_test_project(tmp_path)
    server, thread, base_url = _start_server(module, repo_root, project)

    try:
        # 1. First change the owner in the contract
        status, data = _request_json("POST", f"{base_url}/api/action", 
                                    payload={"action": "set_owner:task-1:gemini-cli"}, 
                                    base_url=base_url)
        assert status == 200
        assert data["ok"] is True

        # 2. Now enqueue task-1 to gemini-cli
        status, data = _request_json("POST", f"{base_url}/api/action", 
                                    payload={"action": "enqueue_task:task-1:gemini-cli"}, 
                                    base_url=base_url)
        assert status == 200
        if data.get("exit_code") != 0:
            print(f"DEBUG gemini-enqueue stderr: {data.get('stderr')}")
        assert data["exit_code"] == 0
        
        # Verify it exists in the inbox for gemini-cli
        inbox = yaml.safe_load((project / ".superharness" / "inbox.yaml").read_text())
        item = next(i for i in inbox if i["task"] == "task-1")
        assert item["to"] == "gemini-cli"

    finally:
        server.shutdown()
        server.server_close()
        thread.join()
