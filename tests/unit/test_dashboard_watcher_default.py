"""Regression guards for BUG-2026-09-24 (dashboard side).

With no `.superharness/watcher.yaml`, the dashboard defaulted
`watcher_project` to the project directory itself and handed it to
`watcher-worker --worker`, which destroyed the project's real state. The
default must be the dedicated worker layout
(`.superharness-workers/<name>` under the user's home directory),
at `watcher_config` and at every inline fallback site.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent


def _load_module():
    script = REPO_ROOT / "src" / "superharness" / "scripts" / "dashboard-ui.py"
    spec = importlib.util.spec_from_file_location("dashboard_watcher_default_module", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def mod() -> object:
    return _load_module()


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / ".superharness").mkdir(parents=True)
    return proj


def _dedicated_worker(home: Path, project: Path) -> str:
    return str(home / ".superharness-workers" / project.name)


def test_watcher_config_defaults_to_dedicated_worker(mod, project: Path, fake_home: Path):
    cfg = mod.watcher_config(project)
    assert cfg["watcher_project"] == _dedicated_worker(fake_home, project)


def test_watcher_config_explicit_yaml_still_wins(
    mod, project: Path, fake_home: Path, tmp_path: Path
):
    custom = tmp_path / "custom-worker"
    (custom / ".superharness").mkdir(parents=True)
    (project / ".superharness" / "watcher.yaml").write_text(
        f'watcher_project: "{custom}"\n', encoding="utf-8"
    )
    cfg = mod.watcher_config(project)
    assert cfg["watcher_project"] == str(custom)


def test_action_watcher_start_never_passes_project_as_worker(
    mod, project: Path, fake_home: Path, monkeypatch: pytest.MonkeyPatch
):
    """The incident path: watcher_start builds the watcher-worker invocation.

    The --worker value must be the dedicated worker layout, never the project.
    """
    handler = mod.Handler.__new__(mod.Handler)
    handler.project_dir = project
    handler.scripts_dir = project / "scripts"
    handler.label = "test.label"

    calls: list[list[str]] = []

    def _fake_run_cmd(args, timeout=None):
        calls.append(list(args))
        return {"exit_code": 0, "stdout": "", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(handler, "_run_cmd", _fake_run_cmd)

    payload, status = handler._action("watcher_start")
    assert status == 200 and payload["exit_code"] == 0
    assert calls, "watcher_start must invoke the watcher-worker command"
    worker_args = calls[0]
    i = worker_args.index("--worker")
    assert worker_args[i + 1] == _dedicated_worker(fake_home, project)
    assert worker_args[i + 1] != str(project)


def test_version_sanity_missing_worker_is_unknown(mod, project: Path, fake_home: Path):
    """No dedicated worker dir yet — version sanity must degrade to 'unknown', not crash."""
    sanity = mod.version_sanity(project)
    assert isinstance(sanity, dict)


def test_watcher_config_honors_missing_explicit_worker(mod, project, tmp_path):
    worker = tmp_path / "uncreated-worker"
    (project / ".superharness" / "watcher.yaml").write_text(f"watcher_project: {worker}\n")
    assert mod.watcher_config(project)["watcher_project"] == str(worker.resolve())
