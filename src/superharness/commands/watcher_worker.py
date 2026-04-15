"""watcher-worker command — create/refresh a clean watcher worker directory."""
from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path



def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="watcher-worker",
        description="Create/refresh a clean watcher worker directory and install the watcher.")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("-w", "--worker", default="")
    p.add_argument("-i", "--interval", type=int, default=15)
    p.add_argument("--recover-timeout-minutes", type=int, default=3, dest="recover_timeout")
    p.add_argument("--recover-action", default="retry", choices=["stale", "retry"], dest="recover_action")
    p.add_argument("--launcher-timeout", type=int, default=180, dest="launcher_timeout")
    p.add_argument("--to", default="both", choices=["both", "claude-code", "codex-cli"])
    p.add_argument("--codex-bypass", action="store_true")
    opts = p.parse_args(argv)

    project_dir = Path(opts.project).resolve()
    if not project_dir.is_dir():
        sys.exit(f"Project directory does not exist: {opts.project}")
    if not (project_dir / ".superharness").is_dir():
        sys.exit(f"Missing .superharness in project: {project_dir}")

    package_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    root = Path(__file__).resolve().parent.parent.parent.parent
    legacy_repo_scripts_dir = root / "scripts"
    project_scripts_dir = project_dir / "scripts"

    if project_scripts_dir.is_dir():
        scripts_dir = project_scripts_dir
    elif package_scripts_dir.is_dir():
        scripts_dir = package_scripts_dir
    else:
        scripts_dir = legacy_repo_scripts_dir

    worker_dir = Path(opts.worker).resolve() if opts.worker else (
        Path.home() / ".superharness-workers" / project_dir.name
    )
    worker_dir.mkdir(parents=True, exist_ok=True)
    worker_dir = worker_dir.resolve()

    # Copy project files (excluding .git, .superharness, etc.)
    from superharness.engine.platform_runtime import sync_worker_copy
    sync_worker_copy(str(project_dir), str(worker_dir))

    # Symlink .superharness -> source project's .superharness
    sh_link = worker_dir / ".superharness"
    if sh_link.exists() and not sh_link.is_symlink():
        shutil.rmtree(str(sh_link))
    if sh_link.is_symlink():
        sh_link.unlink()
    try:
        os.symlink(str(project_dir / ".superharness"), str(sh_link))
    except OSError as e:
        print(f"Warning: could not create .superharness symlink: {e}", file=sys.stderr)  # shipguard:ignore PY-007

    # Install watcher via OS-aware service installer
    from superharness.engine.service_installer import install as _install_service
    _install_service(
        project_dir=project_dir,
        worker_dir=worker_dir,
        scripts_dir=scripts_dir,
        interval=opts.interval,
        recover_timeout=opts.recover_timeout,
        recover_action=opts.recover_action,
        launcher_timeout=opts.launcher_timeout,
        to=opts.to,
        codex_bypass=opts.codex_bypass,
    )

    # Write watcher.yaml
    from superharness.engine.runtime_probe import probe_runtime, persist_runtime
    chosen_interpreter = probe_runtime()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    watcher_cfg = project_dir / ".superharness" / "watcher.yaml"
    watcher_cfg.write_text(
        f'watcher_project: "{worker_dir}"\n'
        f'updated_at: "{now}"\n'
        f"interval_seconds: {opts.interval}\n"
        f"recover_timeout_minutes: {opts.recover_timeout}\n"
        f"recover_action: {opts.recover_action}\n"
        f"launcher_timeout_seconds: {opts.launcher_timeout}\n"
        f"target: {opts.to}\n"
        f"codex_bypass: {'true' if opts.codex_bypass else 'false'}\n",
        encoding="utf-8"
    )
    persist_runtime(watcher_cfg, chosen_interpreter)

    print("Watcher worker is ready.")
    print(f"  Source project : {project_dir}")
    print(f"  Worker project : {worker_dir}")
    print(f"  Config written : {watcher_cfg}")
    print(f"  Interval       : {opts.interval}s")
    print(f"  Recover timeout: {opts.recover_timeout}m")
    print(f"  Recover action: {opts.recover_action}")
    print(f"  Launcher timeout: {opts.launcher_timeout}s")
    if opts.codex_bypass:
        print("  Codex bypass  : enabled")
    else:
        print("  Codex bypass  : disabled")


if __name__ == "__main__":
    main()
