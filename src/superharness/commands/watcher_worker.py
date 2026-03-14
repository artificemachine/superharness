"""watcher-worker command — create/refresh a clean watcher worker directory."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


_EXCLUDE = {".git", ".superharness", ".venv", "node_modules", ".pytest_cache"}


def _copy_tree(src: Path, dst: Path) -> None:
    """Copy src -> dst excluding _EXCLUDE dirs, compatible with Python 3.11+."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in _EXCLUDE:
            continue
        target = dst / item.name
        if item.is_symlink():
            if target.exists() or target.is_symlink():
                target.unlink()
            os.symlink(os.readlink(item), target)
        elif item.is_dir():
            _copy_tree(item, target)
        else:
            shutil.copy2(str(item), str(target))


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

    root = Path(__file__).resolve().parent.parent.parent.parent
    if not (project_dir / "scripts").is_dir():
        scripts_dir = root / "scripts"
    else:
        scripts_dir = project_dir / "scripts"

    worker_dir = Path(opts.worker).resolve() if opts.worker else (
        Path.home() / ".superharness-workers" / project_dir.name
    )
    worker_dir.mkdir(parents=True, exist_ok=True)
    worker_dir = worker_dir.resolve()

    # Copy project files (excluding .git, .superharness, etc.)
    # Try rsync first (macOS/Linux), fall back to Python
    rsync = shutil.which("rsync")
    if rsync and platform.system() != "Windows":
        subprocess.run([
            rsync, "-a", "--delete",
            "--exclude=.git", "--exclude=.superharness", "--exclude=.venv",
            "--exclude=node_modules", "--exclude=.pytest_cache",
            f"{project_dir}/", f"{worker_dir}/"
        ], check=True)
    else:
        # Remove existing (except .superharness symlink)
        for child in list(worker_dir.iterdir()):
            if child.name == ".superharness":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(str(child))
            else:
                child.unlink(missing_ok=True)
        _copy_tree(project_dir, worker_dir)

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

    # Install watcher (macOS launchd only)
    install_script = scripts_dir / "install-launchd-inbox-watcher.sh"
    if platform.system() == "Darwin" and install_script.is_file():
        install_args = [
            "bash", str(install_script),
            "--project", str(worker_dir),
            "--interval", str(opts.interval),
            "--recover-timeout-minutes", str(opts.recover_timeout),
            "--recover-action", opts.recover_action,
            "--launcher-timeout", str(opts.launcher_timeout),
            "--to", opts.to,
            "--confirm-non-interactive", "yes",
            "--confirm-skip-permissions", "yes",
        ]
        if opts.codex_bypass:
            install_args += ["--codex-bypass", "--confirm-codex-bypass", "yes"]
        subprocess.run(install_args, check=False)
    elif platform.system() != "Darwin":
        print(f"INFO: launchd watcher install skipped on {platform.system()}.")
        print("      Use 'superharness watch --foreground --project .' to run the watcher manually.")

    # Write watcher.yaml
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
