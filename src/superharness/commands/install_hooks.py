"""shux install-hooks — merge adapter hook entries into ~/.claude/settings.json.

Reads hooks.json from the adapter directory, resolves ${CLAUDE_PLUGIN_ROOT}
to the actual hooks directory on this machine, and upserts the entries into
the target settings file (default: ~/.claude/settings.json).

Safe to run multiple times — idempotent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


def _is_ephemeral(path: Path) -> bool:
    """Return True if *path* lives under the system temp directory.

    When superharness runs from a git worktree that was created under /tmp
    (as Claude Code does for isolated task branches), ``__file__`` resolves to
    that ephemeral path.  Baking it into settings.json is wrong — it becomes a
    dead path the moment the worktree is deleted.
    """
    tmp_prefix = Path(tempfile.gettempdir()).resolve()
    try:
        return path.resolve().is_relative_to(tmp_prefix)
    except (ValueError, AttributeError):
        return str(path.resolve()).startswith(str(tmp_prefix))


def _find_installed_hooks_dir() -> Path | None:
    """Find hooks inside the pipx/pip-installed package by locating the binary on PATH.

    Resolves the ``shux`` or ``superharness`` symlink to the real binary inside
    the venv, then walks up to site-packages.  This is independent of ``__file__``
    so it stays correct even when this module is loaded from a dev repo via
    PYTHONPATH — a scenario that previously caused the repo source path to be
    written to settings.json.

    Returns None if no installed binary is found.
    """
    import shutil
    for binary in ("shux", "superharness"):
        bin_path = shutil.which(binary)
        if not bin_path:
            continue
        real_bin = Path(bin_path).resolve()
        # pipx layout: …/venvs/<pkg>/bin/<binary>  → venv root is parent of bin/
        venv_root = real_bin.parent.parent
        for candidate in sorted(
            venv_root.glob("lib/*/site-packages/superharness/adapters/claude-code/hooks")
        ):
            if candidate.is_dir() and not _is_ephemeral(candidate):
                return candidate
    return None


def _find_hooks_dir() -> Path:
    """Locate the adapter hooks directory.

    Checks locations in order, preferring the installed package over a dev repo
    so the path written to settings.json is always stable:

    1. Installed binary on PATH (pipx/pip install) — independent of __file__.
    2. In-package path derived from __file__ (regular pip install without shux on PATH).
    3. Editable install (repo checkout, no binary installed elsewhere).

    Paths that resolve into the system temp directory are skipped — they indicate
    an ephemeral git worktree whose path must not be baked into settings.json.
    """
    # 1. Prefer the installed binary's venv — immune to PYTHONPATH overrides
    installed = _find_installed_hooks_dir()
    if installed is not None:
        return installed

    # 2. In-package location: __file__ is at <package>/commands/install_hooks.py
    in_package = Path(__file__).resolve().parent.parent / "adapters" / "claude-code" / "hooks"
    if in_package.is_dir() and not _is_ephemeral(in_package):
        return in_package

    # 3. Editable install: repo root is 3 levels up from src/superharness/commands/
    editable = Path(__file__).resolve().parents[3] / "adapters" / "claude-code" / "hooks"
    if editable.is_dir() and not _is_ephemeral(editable):
        return editable

    raise FileNotFoundError(
        f"Adapter hooks directory not found. "
        "Ensure superharness is installed with 'pip install superharness' or 'pip install -e .' from the repo root."
    )


def _load_hooks_json(hooks_dir: Path) -> dict:
    hooks_json = hooks_dir / "hooks.json"
    if not hooks_json.exists():
        raise FileNotFoundError(f"hooks.json not found at {hooks_json}")
    return json.loads(hooks_json.read_text())


def _load_settings(settings_file: Path) -> dict:
    if settings_file.exists():
        text = settings_file.read_text().strip()
        if text:
            return json.loads(text)
    return {}


def _write_settings(settings_file: Path, data: dict) -> None:
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    dir_ = str(settings_file.parent)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=dir_)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, settings_file)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def _hook_name(command: str) -> str:
    """Normalize a hook command to its bare hook name for identity matching.

    Handles both the legacy form (``bash /abs/path/session-start.sh``) and the
    stable form (``shux hook session-start``) — both normalize to
    ``session-start`` so re-running install-hooks upgrades old entries in place.
    """
    if not command.strip():
        return ""
    return os.path.basename(command.strip().split()[-1]).removesuffix(".sh")


# Back-compat alias (older callers/tests referenced this name).
_script_basename = _hook_name


def _shux_invocation() -> str:
    """Return a stable ``shux`` invocation for hook commands.

    Prefers the absolute path to the installed ``shux`` binary. The binary lives
    at the venv *root* (``…/uv/tools/superharness/bin/shux``), which is stable
    across Python minor-version bumps — unlike ``…/lib/pythonX.Y/site-packages``,
    whose version component uv rewrites on upgrade (breaking baked-in hook paths
    on Linux). Falls back to the bare name ``shux`` if not resolvable on PATH.
    """
    import shutil
    return shutil.which("shux") or "shux"


def merge_hooks(settings: dict, hook_defs: dict, hooks_dir: str) -> tuple[dict, list[str]]:
    """Upsert hook entries from hook_defs into settings.

    Emits version-independent ``shux hook <name>`` commands rather than baking an
    absolute versioned venv path into the config. ``hooks_dir`` is retained for
    signature compatibility but no longer determines the written command.

    Returns (updated_settings, list_of_change_descriptions).
    """
    if "hooks" not in settings:
        settings["hooks"] = {}

    shux = _shux_invocation()
    changes: list[str] = []

    for event, template_entries in hook_defs.get("hooks", {}).items():
        if event not in settings["hooks"]:
            settings["hooks"][event] = []

        for template_entry in template_entries:
            for template_hook in template_entry.get("hooks", []):
                name = _hook_name(template_hook.get("command", ""))
                if not name:
                    continue
                resolved_cmd = f"{shux} hook {name}"

                # Find existing hook entry by normalized name (upgrades legacy paths).
                found = False
                for existing_entry in settings["hooks"][event]:
                    for existing_hook in existing_entry.get("hooks", []):
                        if name == _hook_name(existing_hook.get("command", "")):
                            old_cmd = existing_hook["command"]
                            existing_hook["command"] = resolved_cmd
                            existing_hook["timeout"] = template_hook.get("timeout", existing_hook.get("timeout", 5))
                            found = True
                            if old_cmd != resolved_cmd:
                                changes.append(f"  updated {event}/{name}: {old_cmd!r} → {resolved_cmd!r}")
                            break
                    if found:
                        break

                if not found:
                    settings["hooks"][event].append({
                        "matcher": template_entry.get("matcher", ""),
                        "hooks": [{
                            "type": template_hook.get("type", "command"),
                            "command": resolved_cmd,
                            "timeout": template_hook.get("timeout", 5),
                        }],
                    })
                    changes.append(f"  added {event}/{name}: {resolved_cmd!r}")

    return settings, changes


def _home_dir() -> Path:
    return Path(os.environ["HOME"]) if "HOME" in os.environ else Path.home()


# Target host → default hook-config file (relative to $HOME).
_TARGET_FILES: dict[str, tuple[str, ...]] = {
    "claude": (".claude", "settings.json"),
    "codex": (".codex", "hooks.json"),
}


def install_hooks(
    settings_file: Path | None = None,
    hooks_dir: Path | None = None,
    targets: list[str] | None = None,
) -> int:
    """Install/refresh superharness hooks into one or more agent hook configs.

    ``targets`` selects which agents to write (``claude`` and/or ``codex``).
    When ``settings_file`` is given it overrides the target file (single target).
    """
    if hooks_dir is None:
        try:
            hooks_dir = _find_hooks_dir()
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    try:
        hook_defs = _load_hooks_json(hooks_dir)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Resolve the list of target files to write.
    if settings_file is not None:
        files = [settings_file]
    else:
        files = [_home_dir().joinpath(*_TARGET_FILES[t]) for t in (targets or ["claude"])]

    for target_file in files:
        settings = _load_settings(target_file)
        updated, changes = merge_hooks(settings, hook_defs, str(hooks_dir))
        _write_settings(target_file, updated)
        if changes:
            print(f"install-hooks: updated {target_file}")
            for line in changes:
                print(line)
        else:
            print(f"install-hooks: {target_file} already up to date")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge superharness adapter hooks into ~/.claude/settings.json."
    )
    parser.add_argument(
        "--settings-file",
        type=Path,
        default=None,
        help="Explicit target file (overrides --target). Default: ~/.claude/settings.json",
    )
    parser.add_argument(
        "--target",
        choices=("claude", "codex", "all"),
        default="claude",
        help="Which agent hook config to write: claude (default), codex, or all.",
    )
    parser.add_argument(
        "--codex",
        action="store_true",
        help="Shortcut for --target codex.",
    )
    parser.add_argument(
        "--hooks-dir",
        type=Path,
        default=None,
        help="Override the adapter hooks directory (default: auto-detected from install path)",
    )
    opts = parser.parse_args(argv)
    target = "codex" if opts.codex else opts.target
    targets = ["claude", "codex"] if target == "all" else [target]
    return install_hooks(
        settings_file=opts.settings_file,
        hooks_dir=opts.hooks_dir,
        targets=targets,
    )


if __name__ == "__main__":
    sys.exit(main())
