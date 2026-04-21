"""shux workflow — read/write project-level workflow policy in profile.yaml.

Non-interactive (flag-based):
    shux workflow --autonomy oversight
    shux workflow --default-preset quick
    shux workflow --require-tdd / --no-require-tdd
    shux workflow --show
    shux workflow --show --json

Interactive (TTY, no flags):
    shux workflow   — runs a 3-question questionnaire
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

VALID_AUTONOMY = ("ai_driven", "oversight", "hands_on")
VALID_PRESETS = ("implementation", "quick", "discussion", "review", "approval", "note")

_AUTONOMY_LABELS = {
    "ai_driven": "AI does everything (auto-approves plans, dispatches itself). You observe.",
    "oversight": "AI works, you approve plans and close tasks.",
    "hands_on":  "AI works, you gate every transition.",
}
_PRESET_LABELS = {
    "implementation": "TDD-friendly, full lifecycle",
    "quick":          "todo → in_progress → done",
    "discussion":     "discussion / async",
    "review":         "peer review cycle",
    "approval":       "explicit approval gate",
    "note":           "documentation only",
}


def _profile_path(project: str) -> Path:
    return Path(project) / ".superharness" / "profile.yaml"


def _load_profile(project: str) -> dict:
    p = _profile_path(project)
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text()) or {}
    except Exception:
        return {}


def _save_profile(project: str, doc: dict) -> None:
    _profile_path(project).write_text(
        yaml.dump(doc, default_flow_style=False, sort_keys=False)
    )


def _effective(profile: dict) -> dict:
    """Return current policy with defaults filled in."""
    wf = profile.get("workflow") or {}
    return {
        "autonomy": str(profile.get("autonomy") or "ai_driven"),
        "workflow": {
            "default_preset": str(wf.get("default_preset") or "implementation"),
            "require_tdd": bool(wf.get("require_tdd", True) if "require_tdd" in wf else True),
        },
    }


def _print_settings(effective: dict) -> None:
    wf = effective["workflow"]
    print(f"autonomy        : {effective['autonomy']}")
    print(f"default_preset  : {wf['default_preset']}")
    print(f"require_tdd     : {wf['require_tdd']}")


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _interactive(project: str) -> None:
    profile = _load_profile(project)
    eff = _effective(profile)

    print("shux workflow — configure project autonomy")
    print("==========================================")
    print()

    print("Who drives this project's task flow?")
    for i, key in enumerate(VALID_AUTONOMY, 1):
        marker = " (current)" if key == eff["autonomy"] else ""
        print(f"  {i}) {key}  — {_AUTONOMY_LABELS[key]}{marker}")
    raw = input("> ").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(VALID_AUTONOMY):
        profile["autonomy"] = VALID_AUTONOMY[int(raw) - 1]
    elif raw in VALID_AUTONOMY:
        profile["autonomy"] = raw
    # else keep existing

    print()
    print("Default workflow preset for new tasks?")
    for i, key in enumerate(VALID_PRESETS, 1):
        marker = " (current)" if key == eff["workflow"]["default_preset"] else ""
        print(f"  {i}) {key}  — {_PRESET_LABELS[key]}{marker}")
    raw = input("> ").strip()
    wf = profile.setdefault("workflow", {})
    if raw.isdigit() and 1 <= int(raw) <= len(VALID_PRESETS):
        wf["default_preset"] = VALID_PRESETS[int(raw) - 1]
    elif raw in VALID_PRESETS:
        wf["default_preset"] = raw

    print()
    current_tdd = eff["workflow"]["require_tdd"]
    yn = input(f"Require TDD red/green/refactor in plan handoffs? [{'Y' if current_tdd else 'y'}/{'n' if current_tdd else 'N'}] ").strip().lower()
    if yn in ("y", "yes"):
        wf["require_tdd"] = True
    elif yn in ("n", "no"):
        wf["require_tdd"] = False

    _save_profile(project, profile)
    print()
    print("Saved to .superharness/profile.yaml.")


def cmd_workflow(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(
        prog="shux workflow",
        description="Read/write project-level workflow policy.",
        add_help=True,
    )
    p.add_argument("--project", "-p", default=None,
                   help="Project directory (default: cwd)")
    p.add_argument("--autonomy", choices=list(VALID_AUTONOMY),
                   help="Set autonomy level")
    p.add_argument("--default-preset", choices=list(VALID_PRESETS),
                   dest="default_preset",
                   help="Set default workflow preset for new tasks")
    p.add_argument("--require-tdd", dest="require_tdd", action="store_true",
                   default=None, help="Require TDD fields in plan handoffs")
    p.add_argument("--no-require-tdd", dest="require_tdd", action="store_false",
                   help="Make TDD fields optional")
    p.add_argument("--show", action="store_true",
                   help="Print current settings")
    p.add_argument("--json", action="store_true",
                   help="Output as JSON (use with --show)")

    opts = p.parse_args(argv if argv is not None else sys.argv[1:])

    project = opts.project or os.getcwd()
    project = os.path.realpath(project)

    has_flags = any([opts.autonomy, opts.default_preset, opts.require_tdd is not None,
                     opts.show])

    # Non-TTY, no flags → print current settings and exit
    if not has_flags and not sys.stdin.isatty():
        profile = _load_profile(project)
        eff = _effective(profile)
        if opts.json:
            print(json.dumps(eff))
        else:
            _print_settings(eff)
        sys.exit(0)

    # No flags, TTY → interactive
    if not has_flags:
        _interactive(project)
        return

    # --show (with optional --json)
    if opts.show:
        profile = _load_profile(project)
        eff = _effective(profile)
        if opts.json:
            print(json.dumps(eff))
        else:
            _print_settings(eff)
        sys.exit(0)

    # Apply flag-based changes
    profile = _load_profile(project)

    if opts.autonomy is not None:
        if opts.autonomy not in VALID_AUTONOMY:
            _abort(
                f"error: --autonomy must be one of: {', '.join(VALID_AUTONOMY)}", 2
            )
        profile["autonomy"] = opts.autonomy

    wf = profile.setdefault("workflow", {})

    if opts.default_preset is not None:
        if opts.default_preset not in VALID_PRESETS:
            _abort(
                f"error: --default-preset must be one of: {', '.join(VALID_PRESETS)}", 2
            )
        wf["default_preset"] = opts.default_preset

    if opts.require_tdd is not None:
        wf["require_tdd"] = bool(opts.require_tdd)

    _save_profile(project, profile)
    print("Saved.")


if __name__ == "__main__":
    cmd_workflow()
