"""CLI for behavioral profile — shux profile show/edit."""
from __future__ import annotations

import json
import os
import sys


def cmd_profile(args: list[str]) -> None:
    """View and manage the learned behavioral profile.

    Usage:
      shux profile show              — show current profile
      shux profile show --format json — machine-readable
      shux profile edit              — edit profile in $EDITOR
      shux profile reset <key>       — delete a pattern (re-learn)
      shux profile lock <key>        — pin a value (never auto-adapt)
      shux profile unlock <key>      — allow auto-adaptation again
    """
    from superharness.engine.behavioral import (
        user_profile_path, load_profile, save_profile, extract_all_profiles,
    )

    if not args:
        # Default: show
        _show_profile()
        return

    subcmd = args[0]

    if subcmd == "show":
        fmt = "text"
        for i, a in enumerate(args):
            if a == "--format" and i + 1 < len(args):
                fmt = args[i + 1]
        _show_profile(fmt)
    elif subcmd == "edit":
        profile_path = os.path.join(user_profile_path(), "task_style.json")
        editor = os.environ.get("EDITOR", "vim")
        os.system(f"{editor} {profile_path}")
    elif subcmd == "reset" and len(args) >= 2:
        key = args[1]
        _reset_key(key)
    elif subcmd == "lock" and len(args) >= 2:
        key = args[1]
        _lock_key(key)
    elif subcmd == "unlock" and len(args) >= 2:
        key = args[1]
        _unlock_key(key)
    else:
        print("Usage: shux profile <show|edit|reset|lock|unlock> [key]")
        sys.exit(1)


def _show_profile(fmt: str = "text") -> None:
    from superharness.engine.behavioral import (
        user_profile_path, load_profile, extract_all_profiles,
    )

    upath = user_profile_path()
    profiles = {}
    for fname in os.listdir(upath) if os.path.isdir(upath) else []:
        if fname.endswith(".json") and not fname.startswith("_"):
            data = load_profile(os.path.join(upath, fname))
            if data:
                profiles[fname.replace(".json", "")] = data

    if fmt == "json":
        print(json.dumps(profiles, indent=2, default=str))
        return

    if not profiles:
        print("No behavioral profile yet.")
        print("The profile builds automatically as you create and review tasks.")
        print("Run: shux profile show --format json  (to see raw data)")
        return

    print("Behavioral Profile (learned from your task history)\n")
    for name, data in profiles.items():
        conf = data.get("confidence", "low")
        count = data.get("sample_count", 0)
        print(f"  {name} ({conf} confidence, {count} samples):")
        for k, v in data.items():
            if k not in ("confidence", "sample_count", "updated_at"):
                print(f"    {k}: {v}")
        print()

    # Also check project-level
    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, ".superharness", "behavioral")):
        print("Project-level profile also exists at .superharness/behavioral/")

    # Check locks
    locks_path = os.path.join(upath, "_locks.json")
    locks = load_profile(locks_path)
    if locks:
        print("Locked keys (never auto-adapted):")
        for k, v in locks.items():
            print(f"  {k} = {v}")


def _reset_key(key: str) -> None:
    from superharness.engine.behavioral import user_profile_path
    upath = user_profile_path()
    for fname in os.listdir(upath):
        if fname.endswith(".json") and not fname.startswith("_"):
            fpath = os.path.join(upath, fname)
            profile = load_profile(fpath)
            if key in profile:
                del profile[key]
                save_profile(fpath, profile)
                print(f"Reset: {key} (will be re-learned from future tasks)")
                return
    print(f"Key '{key}' not found in profile.")


def _lock_key(key: str) -> None:
    from superharness.engine.behavioral import user_profile_path, save_profile, load_profile
    upath = user_profile_path()
    locks_path = os.path.join(upath, "_locks.json")
    locks = load_profile(locks_path)
    locks[key] = "locked"
    save_profile(locks_path, locks)
    print(f"Locked: {key} (will never be auto-adapted)")


def _unlock_key(key: str) -> None:
    from superharness.engine.behavioral import user_profile_path, save_profile, load_profile
    upath = user_profile_path()
    locks_path = os.path.join(upath, "_locks.json")
    locks = load_profile(locks_path)
    if key in locks:
        del locks[key]
        save_profile(locks_path, locks)
        print(f"Unlocked: {key} (auto-adaptation re-enabled)")
    else:
        print(f"Key '{key}' is not locked.")
