from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "src" / "superharness" / "scripts"


def run_bash(script: Path, *, cwd: Path, stdin: str | None = None, env: dict[str, str] | None = None, args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        for k, v in env.items():
            if v is None:
                merged_env.pop(k, None)
            else:
                merged_env[k] = v
    command = ["bash", str(script)]
    if args:
        command.extend(args)
    return subprocess.run(
        command,
        cwd=cwd,
        input=stdin,
        text=True,
        capture_output=True,
        env=merged_env,
        check=False,
    )


def run_cmd(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)


def copy_from_repo(rel_path: str, dest_root: Path) -> Path:
    src = REPO_ROOT / rel_path
    dst = dest_root / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dst.chmod(src.stat().st_mode)
    return dst


def shell_guard_list(repo_root: Path, flag: str) -> list[str]:
    result = run_bash(
        SCRIPTS_DIR / "check-shell-entrypoints.sh",
        cwd=repo_root,
        args=[flag],
    )
    if result.returncode != 0:
        raise RuntimeError(f"check-shell-entrypoints {flag} failed: {result.stderr}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def parse_json_output(stdout: str) -> dict[str, object]:
    return json.loads(stdout)
