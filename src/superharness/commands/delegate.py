"""Python port of delegate.sh.

Builds a prompt for the target agent (claude-code or codex-cli) and either
prints it (--print-only) or launches the CLI.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

def _read_profile_field(project_dir: str, field: str, default: str) -> str:
    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    if not os.path.isfile(profile_file):
        return default
    try:
        import yaml
        with open(profile_file) as f:
            doc = yaml.safe_load(f) or {}
        val = doc.get(field)
        return str(val) if val is not None else default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Contract helpers (direct YAML reads — avoids subprocess for simple fields)
# ---------------------------------------------------------------------------

def _load_contract(contract_file: str) -> dict:
    try:
        import yaml
        with open(contract_file) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        _abort(f"Failed to parse contract: {e}")


def _get_contract_id(contract_file: str) -> str:
    doc = _load_contract(contract_file)
    return str(doc.get("id") or "") or "unknown-contract"


def _get_task_acceptance_criteria(contract_file: str, task_id: str) -> list[str]:
    doc = _load_contract(contract_file)
    tasks = doc.get("tasks") or []
    for t in tasks:
        if isinstance(t, dict) and str(t.get("id", "")) == task_id:
            ac = t.get("acceptance_criteria")
            if isinstance(ac, list):
                return [str(c) for c in ac]
            return []
    return []


def _get_task_title(contract_file: str, task_id: str) -> str:
    doc = _load_contract(contract_file)
    tasks = doc.get("tasks") or []
    for t in tasks:
        if isinstance(t, dict) and str(t.get("id", "")) == task_id:
            return str(t.get("title", ""))
    return ""


def _get_task_field(contract_file: str, task_id: str, field: str) -> str | None:
    """Return a string field from a task, or None if absent."""
    doc = _load_contract(contract_file)
    tasks = doc.get("tasks") or []
    for t in tasks:
        if isinstance(t, dict) and str(t.get("id", "")) == task_id:
            val = t.get(field)
            return str(val) if val is not None else None
    return None


def _get_task_previously_failed(contract_file: str, task_id: str) -> bool:
    status = _get_task_field(contract_file, task_id, "status")
    return status == "failed"


def _get_latest_handoff_task(handoff_dir: str, to: str) -> tuple[str, str]:
    """Returns (task_id, handoff_file) or ("", "")."""
    import glob as _glob
    import yaml

    files = sorted(
        _glob.glob(os.path.join(handoff_dir, "*.yaml")),
        key=os.path.getmtime,
        reverse=True,
    )
    for fpath in files:
        try:
            with open(fpath) as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            _abort(f"Failed to parse handoff {fpath}: {e}")
        if str(data.get("to", "")) != str(to):
            continue
        task_val = str(data.get("task", ""))
        if task_val:
            return task_val, fpath
    return "", ""


# ---------------------------------------------------------------------------
# Discussion round context helpers
# ---------------------------------------------------------------------------

_DISC_ROUND_RE = re.compile(r"^(discuss-[^/]+)/round-(\d+)$")


def _get_round_context(disc_dir: str, round_: int, agent: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "superharness.engine.discussion",
         "round_context",
         "--discussion-dir", disc_dir,
         "--round", str(round_),
         "--agent", agent],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        _abort("Failed to get discussion context")
    import json
    return json.loads(result.stdout)


def _build_prior_context(ctx: dict) -> str:
    lines = []
    for r in ctx.get("prior_rounds") or []:
        lines.append(f"--- Round {r['round']} ---")
        for p in r.get("positions") or []:
            lines.append(f"Agent: {p.get('agent', '')}")
            lines.append(f"Verdict: {p.get('verdict', '')}")
            lines.append(f"Position: {p.get('position', '')}")
            pts = p.get("points") or []
            if isinstance(pts, list) and pts:
                lines.append("Points:")
                for pt in pts:
                    if isinstance(pt, dict):
                        lines.append(f"  - {pt.get('id', '')}: {pt.get('verdict', '')} — {pt.get('rationale', '')}")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Confirmation helpers (mirrors Bash confirm_* functions)
# ---------------------------------------------------------------------------

def _confirm_non_interactive_risk(target: str, codex_bypass: bool) -> None:
    if target == "codex-cli" and codex_bypass:
        risk_msg = "Risk: non-interactive Codex bypass disables sandbox and approval prompts. Continue?"
    else:
        risk_msg = "Risk: non-interactive mode runs without live user supervision. Continue?"

    env_val = os.environ.get("SUPERHARNESS_CONFIRM_NON_INTERACTIVE", "")
    if env_val in ("YES", "yes", "Y", "y"):
        return

    if not sys.stdin.isatty():
        print("Refusing non-interactive launch without explicit confirmation.", file=sys.stderr)
        print("Set SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES to allow unattended launch.", file=sys.stderr)
        sys.exit(1)

    sys.stderr.write(f"{risk_msg} [y/N]: ")
    sys.stderr.flush()
    ans = sys.stdin.readline().strip()
    if ans not in ("y", "Y", "yes", "YES"):
        print("Aborted by user.", file=sys.stderr)
        sys.exit(1)


def _confirm_dangerous_flag_risk(env_name: str, risk_msg: str) -> None:
    env_val = os.environ.get(env_name, "")
    if env_val in ("YES", "yes", "Y", "y"):
        return

    if not sys.stdin.isatty():
        print("Refusing dangerous launch without explicit confirmation.", file=sys.stderr)
        print(f"Set {env_name}=YES to allow this specific bypass.", file=sys.stderr)
        sys.exit(1)

    sys.stderr.write(f"{risk_msg} [y/N]: ")
    sys.stderr.flush()
    ans = sys.stdin.readline().strip()
    if ans not in ("y", "Y", "yes", "YES"):
        print("Aborted by user.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def _launch_agent(
    target: str,
    prompt: str,
    project_dir: str,
    non_interactive: bool,
    codex_bypass: bool,
    label: str = "",
    model: str = "",
    effort: str = "",
) -> None:
    display_label = f" {label}" if label else ""

    if target == "claude-code":
        if not _cmd_exists("claude"):
            _abort("claude CLI is not installed or not on PATH")
        print()

        model_args: list[str] = []
        if model:
            model_args += ["--model", model]
        if effort:
            model_args += ["--effort", effort]

        if non_interactive:
            _confirm_dangerous_flag_risk(
                "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS",
                "Risk: Claude --dangerously-skip-permissions disables permission prompts. Continue?",
            )
            print(f"Launching Claude{display_label}...")
            os.chdir(project_dir)
            os.execvp("claude", ["claude", "-p", "--dangerously-skip-permissions"] + model_args + [prompt])
        print(f"Launching Claude{display_label}...")
        os.chdir(project_dir)
        os.execvp("claude", ["claude"] + model_args + [prompt])

    else:  # codex-cli
        if not _cmd_exists("codex"):
            _abort("codex CLI is not installed or not on PATH")
        print()

        codex_model_args: list[str] = []
        if model:
            codex_model_args += ["--model", model]

        if non_interactive:
            print(f"Launching Codex{display_label}...")
            common = ["exec", "--skip-git-repo-check", "-C", project_dir]
            if codex_bypass:
                _confirm_dangerous_flag_risk(
                    "SUPERHARNESS_CONFIRM_CODEX_BYPASS",
                    "Risk: Codex bypass disables sandbox and approval prompts. Continue?",
                )
                os.execvp("codex", ["codex"] + common + codex_model_args + ["--dangerously-bypass-approvals-and-sandbox", prompt])
            os.execvp("codex", ["codex"] + common + codex_model_args + ["--full-auto", prompt])
        print(f"Launching Codex{display_label}...")
        os.execvp("codex", ["codex", "-C", project_dir] + codex_model_args + [prompt])


def _expand_path() -> None:
    """Augment PATH with common user-local bin dirs — launchd starts with a minimal PATH."""
    import shutil
    extra = [
        os.path.expanduser("~/.local/bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/sbin",
    ]
    current = os.environ.get("PATH", "")
    additions = [p for p in extra if p not in current.split(os.pathsep) and os.path.isdir(p)]
    if additions:
        os.environ["PATH"] = os.pathsep.join(additions) + os.pathsep + current


def _cmd_exists(name: str) -> bool:
    import shutil
    _expand_path()
    return shutil.which(name) is not None


# ---------------------------------------------------------------------------
# Main delegate logic
# ---------------------------------------------------------------------------

def delegate(
    project_dir: str,
    target: str,
    task_id: str,
    print_only: bool,
    non_interactive: bool,
    codex_bypass: bool,
    model_override: str = "",
    effort_override: str = "",
    no_auto_model: bool = False,
) -> int:
    project_dir = os.path.realpath(project_dir)

    harness_dir = os.path.join(project_dir, ".superharness")
    contract_file = os.path.join(harness_dir, "contract.yaml")
    handoff_dir = os.path.join(harness_dir, "handoffs")

    if not os.path.isfile(contract_file):
        _abort(f"Missing contract file: {contract_file}")
    if not os.path.isdir(handoff_dir):
        _abort(f"Missing handoff directory: {handoff_dir}")

    contract_id = _get_contract_id(contract_file)

    latest_handoff = ""
    if not task_id:
        task_id, latest_handoff = _get_latest_handoff_task(handoff_dir, target)
        if not task_id:
            print(
                f"Could not determine task id. Provide --task TASK_ID or create a "  # shipguard:ignore PY-007
                f"{target} handoff in {handoff_dir}",
                file=sys.stderr,
            )
            return 1

    # -----------------------------------------------------------------------
    # Model / effort resolution
    # Order: CLI flag > task field > classifier > profile default > standard/medium
    # -----------------------------------------------------------------------
    resolved_model = ""
    resolved_effort = ""
    model_source = "fallback"

    # 1. CLI flag
    if model_override:
        resolved_model = model_override
        model_source = "manual"
    if effort_override:
        resolved_effort = effort_override

    # 2. Task field (if not already set by CLI)
    if not resolved_model:
        task_model = _get_task_field(contract_file, task_id, "model")
        if task_model:
            resolved_model = task_model
            model_source = "task"
    if not resolved_effort:
        task_effort = _get_task_field(contract_file, task_id, "effort")
        if task_effort:
            resolved_effort = task_effort

    # 3. Auto-classification (if not fully resolved and not disabled)
    if not no_auto_model and (not resolved_model or not resolved_effort):
        try:
            from superharness.engine.model_router import (
                classify_task,
                resolve_model as _resolve_model,
                resolve_tier,
            )
            task_title = _get_task_title(contract_file, task_id)
            ac_for_classify = _get_task_acceptance_criteria(contract_file, task_id)
            previously_failed = _get_task_previously_failed(contract_file, task_id)

            classified_tier, classified_effort = classify_task(
                title=task_title or task_id,
                criteria=ac_for_classify or None,
                previously_failed=previously_failed,
            )
            if not resolved_model:
                resolved_model = _resolve_model(target, classified_tier)
                model_source = "auto-classified"
            if not resolved_effort:
                resolved_effort = classified_effort
        except Exception:
            pass  # classification failure is non-fatal

    # 4. Profile defaults
    if not resolved_model:
        profile_model = _read_profile_field(project_dir, "default_model", "")
        if profile_model:
            try:
                from superharness.engine.model_router import resolve_model as _resolve_model, resolve_tier
                tier = resolve_tier(profile_model)
                if tier:
                    resolved_model = _resolve_model(target, tier)
                else:
                    resolved_model = profile_model
            except Exception:
                resolved_model = profile_model
            model_source = "profile"
    if not resolved_effort:
        profile_effort = _read_profile_field(project_dir, "default_effort", "")
        if profile_effort:
            resolved_effort = profile_effort

    # 5. Hardcoded fallback
    if not resolved_model:
        try:
            from superharness.engine.model_router import resolve_model as _resolve_model
            resolved_model = _resolve_model(target, "standard")
        except Exception:
            resolved_model = "sonnet"
        model_source = "fallback"
    if not resolved_effort:
        resolved_effort = "medium"

    # If model_override was a tier name, resolve to agent-specific model
    try:
        from superharness.engine.model_router import resolve_tier, resolve_model as _resolve_model
        tier = resolve_tier(resolved_model)
        if tier:
            resolved_model = _resolve_model(target, tier)
    except Exception:
        pass

    # Acceptance criteria
    ac_lines = _get_task_acceptance_criteria(contract_file, task_id)
    acceptance_criteria = ""
    if ac_lines:
        ac_block = "\n".join(f"- {c}" for c in ac_lines)
        acceptance_criteria = f"\n\nAcceptance criteria for this task:\n{ac_block}"

    auto_directive = ""
    if non_interactive:
        auto_directive = (
            "\nThis is an automated non-interactive run. "
            "Do not ask for confirmation or approval. "
            "Proceed and apply all changes immediately."
        )

    # Discussion-round detection
    m = _DISC_ROUND_RE.match(task_id)
    discussion_id = m.group(1) if m else ""
    discussion_round = int(m.group(2)) if m else 0

    discussions_dir = os.path.join(harness_dir, "discussions")
    prompt = ""

    if discussion_id and discussion_round:
        disc_dir = os.path.join(discussions_dir, discussion_id)
        if not os.path.isdir(disc_dir):
            _abort(f"Discussion directory not found: {disc_dir}")

        ctx = _get_round_context(disc_dir, discussion_round, target)
        disc_topic = str(ctx.get("topic") or "")
        disc_max = str(ctx.get("max_rounds") or "")
        submit_path = os.path.join(disc_dir, f"round-{discussion_round}-{target}.yaml")

        if discussion_round == 1:
            prompt = (
                f"You are participating in a multi-agent discussion.\n"
                f"Topic: {disc_topic}\n"
                f"You are: {target}\n"
                f"This is round {discussion_round} of {disc_max}.\n"
                f"\n"
                f"Review the topic and write your position. Be specific about what you agree or disagree with.\n"
                f"\n"
                f"When done, write a YAML file to: {submit_path}\n"
                f"The file must have these fields:\n"
                f"  discussion_id: {discussion_id}\n"
                f"  round: {discussion_round}\n"
                f"  agent: {target}\n"
                f"  verdict: agree OR disagree OR partial\n"
                f"  position: your free-form analysis\n"
                f"  points: list of {{id, verdict, rationale}} for each sub-point\n"
                f"  submitted_at: (current UTC ISO 8601 timestamp)\n"
                f"\n"
                f"If you agree with everything, set verdict: agree. "
                f"Otherwise set verdict: disagree or partial and explain in points.\n"
                f"Read .superharness/discussions/{discussion_id}/state.yaml for the full discussion context.\n"
                f"Read the handoff referenced in .superharness/contract.yaml for the task details."
                f"{auto_directive}"
            )
        else:
            prior_context = _build_prior_context(ctx)
            prompt = (
                f"You are participating in a multi-agent discussion.\n"
                f"Topic: {disc_topic}\n"
                f"You are: {target}\n"
                f"This is round {discussion_round} of {disc_max}.\n"
                f"\n"
                f"Here are the positions from prior rounds:\n"
                f"{prior_context}\n"
                f"\n"
                f"Consider the other agent's position carefully. "
                f"If you now agree with all points, set verdict: agree.\n"
                f"If you still disagree, explain specifically what remains unresolved.\n"
                f"\n"
                f"Write your response to: {submit_path}\n"
                f"The file must have these fields:\n"
                f"  discussion_id: {discussion_id}\n"
                f"  round: {discussion_round}\n"
                f"  agent: {target}\n"
                f"  verdict: agree OR disagree OR partial\n"
                f"  position: your free-form analysis\n"
                f"  points: list of {{id, verdict, rationale}} for each sub-point\n"
                f"  submitted_at: (current UTC ISO 8601 timestamp)\n"
                f"\n"
                f"Read .superharness/discussions/{discussion_id}/state.yaml for full context."
                f"{auto_directive}"
            )

        print(f"Project: {project_dir}")
        print(f"Discussion: {discussion_id}")
        print(f"Round: {discussion_round}")
        print(f"Agent: {target}")
        print(f"Topic: {disc_topic}")

    else:
        if target == "claude-code":
            if latest_handoff:
                prompt = (
                    f"continue contract\n"
                    f"Read the latest handoff addressed to claude-code and execute task {task_id}.\n"
                    f"Use scope, commands, and acceptance criteria from the handoff.\n"
                    f"Update .superharness/contract.yaml task status, append .superharness/ledger.md, "  # shipguard:ignore PY-007
                    f"and refresh the handoff with outcomes.\n"
                    f"Contract id: {contract_id}."
                    f"{acceptance_criteria}{auto_directive}"
                )
            else:
                prompt = (
                    f"continue contract\n"
                    f"No handoff exists yet for task {task_id}.\n"
                    f"Read .superharness/contract.yaml directly and execute task {task_id}.\n"
                    f"Update .superharness/contract.yaml task status, append .superharness/ledger.md, "  # shipguard:ignore PY-007
                    f"and create a new handoff with outcomes.\n"  # shipguard:ignore PY-007
                    f"Contract id: {contract_id}."
                    f"{acceptance_criteria}{auto_directive}"
                )
        else:  # codex-cli
            if latest_handoff:
                prompt = (
                    f"continue contract\n"
                    f"Read the latest handoff addressed to codex-cli and execute task {task_id}.\n"
                    f"Use scope, commands, and acceptance criteria from the handoff.\n"
                    f"Update .superharness/contract.yaml task status, append .superharness/ledger.md, "  # shipguard:ignore PY-007
                    f"and refresh the handoff with outcomes.\n"
                    f"Contract id: {contract_id}."
                    f"{acceptance_criteria}"
                )
            else:
                prompt = (
                    f"continue contract\n"
                    f"No handoff exists yet for task {task_id}.\n"
                    f"Read .superharness/contract.yaml directly and execute task {task_id}.\n"
                    f"Update .superharness/contract.yaml task status, append .superharness/ledger.md, "  # shipguard:ignore PY-007
                    f"and create a new handoff with outcomes.\n"  # shipguard:ignore PY-007
                    f"Contract id: {contract_id}."
                    f"{acceptance_criteria}"
                )

        # Enrich prompt with vault context
        task_title = _get_task_title(contract_file, task_id)
        try:
            from superharness.engine.osm import vault_search
            vault_results = vault_search(task_title or task_id)
            if vault_results:
                vault_block = "\n\nVault notes relevant to this task (via obsidian-semantic):\n"
                for r in vault_results:
                    preview = r.get("preview", "")[:120].replace("\n", " ")
                    vault_block += f"  - {r['path']} (similarity: {r['similarity']})\n    {preview}\n"
                prompt += vault_block
        except Exception:
            pass

        print(f"Project: {project_dir}")
        print(f"Contract: {contract_id}")
        print(f"Task: {task_id}")
        if latest_handoff:
            print(f"Handoff: {latest_handoff}")

    print(f"Model: {resolved_model} ({model_source})")
    print(f"Effort: {resolved_effort}")

    if print_only:
        print()
        print("Generated prompt:")
        print("-----------------")
        print(prompt)
        return 0

    if non_interactive:
        _confirm_non_interactive_risk(target, codex_bypass)

    label = f"for discussion round {discussion_round}" if discussion_id else ""
    _launch_agent(
        target, prompt, project_dir, non_interactive, codex_bypass,
        label=label, model=resolved_model, effort=resolved_effort,
    )
    return 0  # unreachable after exec, but satisfies type checker


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    class _CapUsage(argparse.HelpFormatter):
        def _format_usage(self, usage, actions, groups, prefix):
            return super()._format_usage(usage, actions, groups, "Usage: ")

    parser = argparse.ArgumentParser(
        prog="delegate",
        description="Build prompt for target agent and launch or print it",
        formatter_class=_CapUsage,
        add_help=True,
    )
    parser.add_argument("--to", required=True, dest="target")
    parser.add_argument("--project", "-p", default=None)
    parser.add_argument("--task", "-t", default="")
    parser.add_argument("--print-only", action="store_true", default=False)
    parser.add_argument("--non-interactive", action="store_true", default=False)
    parser.add_argument("--codex-bypass", action="store_true", default=False)
    parser.add_argument(
        "--model", default=None,
        help="Override model. Accepts tier (mini/standard/max) or model name (sonnet, gpt-5.3-codex, etc.)",
    )
    parser.add_argument(
        "--effort", default=None,
        choices=["low", "medium", "high"],
        help="Override thinking effort (low/medium/high)",
    )
    parser.add_argument(
        "--no-auto-model", action="store_true", default=False,
        help="Skip auto-classification, use profile defaults or standard/medium",
    )

    opts = parser.parse_args(argv)

    if opts.target not in ("claude-code", "codex-cli"):
        print("--to must be claude-code or codex-cli", file=sys.stderr)
        sys.exit(2)

    project_dir = os.path.realpath(opts.project or os.getcwd())
    if not os.path.isdir(project_dir):
        print(f"Project directory does not exist: {project_dir}", file=sys.stderr)
        sys.exit(1)

    # Apply autonomy from profile (mirrors Bash export logic)
    autonomy = _read_profile_field(project_dir, "autonomy", "approval-gated")
    if autonomy == "autonomous":
        os.environ.setdefault("SUPERHARNESS_CONFIRM_NON_INTERACTIVE", "YES")
        os.environ.setdefault("SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS", "YES")
    elif autonomy == "supervised":
        os.environ.setdefault("SUPERHARNESS_CONFIRM_NON_INTERACTIVE", "YES")

    rc = delegate(
        project_dir=project_dir,
        target=opts.target,
        task_id=opts.task,
        print_only=opts.print_only,
        non_interactive=opts.non_interactive,
        codex_bypass=opts.codex_bypass,
        model_override=opts.model or "",
        effort_override=opts.effort or "",
        no_auto_model=opts.no_auto_model,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
