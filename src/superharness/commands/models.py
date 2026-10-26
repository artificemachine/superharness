"""shux models — check and maintain superharness's own model bindings file.

The bindings file decides which model each harness uses per tier. It lives
in superharness's config directory (`SUPERHARNESS_CONFIG_DIR`, else
`$XDG_CONFIG_HOME/superharness/model-bindings.yaml`); superharness reads no
other tool's configuration.

Exit codes for `check`: 0 fresh, 1 stale or invalid, 2 missing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from typing import Any

import click

from superharness.engine.model_bindings import BindingsFile, load_bindings, stale_providers

EXIT_OK = 0
EXIT_ATTENTION = 1
EXIT_MISSING = 2


def _bindings_file() -> BindingsFile:
    from superharness.engine.model_router import _runtime_model_bindings_path

    return load_bindings(_runtime_model_bindings_path())


def _binding_rows(bindings: BindingsFile) -> list[dict[str, str]]:
    """One row per bound tier of each harness's default provider."""
    rows: list[dict[str, str]] = []
    harnesses = bindings.data.get("harnesses")
    if not isinstance(harnesses, dict):
        return rows
    for harness in sorted(harnesses):
        entry = harnesses[harness]
        if not isinstance(entry, dict):
            continue
        provider = entry.get("default_provider")
        all_bindings = entry.get("bindings")
        if not isinstance(provider, str) or not isinstance(all_bindings, dict):
            continue
        provider_bindings = all_bindings.get(provider)
        if not isinstance(provider_bindings, dict):
            continue
        for tier, binding in provider_bindings.items():
            model = binding.get("id") if isinstance(binding, dict) else None
            if isinstance(model, str) and model.strip():
                rows.append(
                    {"harness": harness, "provider": provider, "tier": str(tier), "model": model.strip()}
                )
    return rows


def classify_bindings(
    rows: list[dict[str, str]], discovered_by_harness: dict[str, list[str] | Exception]
) -> list[dict[str, str]]:
    """Mark each binding row available, unavailable or unknown from discovery results.

    An empty discovery answer means discovery could not tell, so the binding
    is ``unknown``; an exception is ``unknown`` with its message in ``error``.
    """
    classified = []
    for row in rows:
        answer = discovered_by_harness.get(row["harness"], [])
        out = dict(row)
        if isinstance(answer, Exception):
            out["availability"] = "unknown"
            out["error"] = f"{type(answer).__name__}: {answer}"
        elif not answer:
            out["availability"] = "unknown"
        else:
            out["availability"] = "available" if row["model"] in answer else "unavailable"
        classified.append(out)
    return classified


def _discover_bound_models(rows: list[dict[str, str]]) -> dict[str, list[str] | Exception]:
    """Run discovery once per harness, asking about that harness's bound models."""
    from superharness.engine import model_router

    by_harness: dict[str, list[str]] = {}
    for row in rows:
        by_harness.setdefault(row["harness"], [])
        if row["model"] not in by_harness[row["harness"]]:
            by_harness[row["harness"]].append(row["model"])

    results: dict[str, list[str] | Exception] = {}
    for harness, models in by_harness.items():
        try:
            auth_mode = model_router.detect_auth_mode_for_agent(harness)
            found = model_router._discover_for_agent(harness, auth_mode, models)
            results[harness] = [d.id for d in found]
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            # One harness's failing probe must not hide the others' results.
            results[harness] = exc
    return results


def _check_report(bindings: BindingsFile, today: date) -> tuple[dict[str, Any], int]:
    if bindings.status == "missing":
        report = {"path": str(bindings.path), "status": "missing", "reason": bindings.reason,
                  "stale_providers": [], "bindings": []}
        return report, EXIT_MISSING
    if bindings.status == "invalid":
        report = {"path": str(bindings.path), "status": "invalid", "reason": bindings.reason,
                  "stale_providers": [], "bindings": []}
        return report, EXIT_ATTENTION
    stale = stale_providers(bindings, today)
    report = {
        "path": str(bindings.path),
        "status": "stale" if stale else "ok",
        "reason": "",
        "stale_providers": stale,
        "bindings": _binding_rows(bindings),
    }
    return report, EXIT_ATTENTION if stale else EXIT_OK


def _print_report(report: dict[str, Any]) -> None:
    click.echo(f"Model bindings: {report['path']}")
    status = report["status"]
    if status == "missing":
        click.echo("Status: missing — adapter defaults are used for every harness.")
        return
    if status == "invalid":
        click.echo(f"Status: invalid — {report['reason']}")
        click.echo("Dispatch ignores this file and uses adapter defaults until it is fixed.")
        return
    click.echo(f"Status: {status}")
    if report["stale_providers"]:
        click.echo(f"Stale providers: {', '.join(report['stale_providers'])}")
    for row in report["bindings"]:
        availability = f"  [{row['availability']}]" if "availability" in row else ""
        error = f"  {row['error']}" if row.get("error") else ""
        click.echo(
            f"  {row['harness']:<14} {row['tier']:<13} {row['model']}  ({row['provider']})"
            f"{availability}{error}"
        )


@click.group()
def main() -> None:
    """Check and maintain superharness's own model bindings file."""


@main.command("check")
@click.option("--probe", is_flag=True, default=False,
              help="Ask harness discovery whether each bound model is available")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON")
def check_cmd(probe: bool, as_json: bool) -> None:
    """Report the bindings file: path, status, bindings and stale providers."""
    report, code = _check_report(_bindings_file(), date.today())
    if probe and report["bindings"]:
        report["bindings"] = classify_bindings(
            report["bindings"], _discover_bound_models(report["bindings"])
        )
        if any(row["availability"] == "unavailable" for row in report["bindings"]):
            code = max(code, EXIT_ATTENTION)
    if as_json:
        click.echo(json.dumps(report, indent=2))
    else:
        _print_report(report)
    sys.exit(code)


if __name__ == "__main__":
    main()
