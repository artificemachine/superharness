"""shux models — check and maintain superharness's own model bindings file.

The bindings file decides which model each harness uses per tier. It lives
in superharness's config directory (`SUPERHARNESS_CONFIG_DIR`, else
`$XDG_CONFIG_HOME/superharness/model-bindings.yaml`); superharness reads no
other tool's configuration.

Exit codes for `check`: 0 fresh, 1 stale or invalid, 2 missing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import click
import yaml

from superharness.engine.model_bindings import (
    CATALOG_REFRESH_COMMAND,
    DEFAULT_REVIEW_AFTER_DAYS,
    DISPATCH_TO_BINDING_TIER,
    SCHEMA_VERSION,
    BindingsFile,
    load_bindings,
    stale_providers,
)

MANIFEST_PROVIDER = "adapter-manifest"

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


_BINDING_TO_DISPATCH_TIER = {binding: dispatch for dispatch, binding in DISPATCH_TO_BINDING_TIER.items()}


def _models_by_harness(
    rows: list[dict[str, str]], extra: dict[tuple[str, str], list[str]] | None = None
) -> dict[str, list[str]]:
    """Bound models per harness, followed by any extra candidates, without duplicates."""
    by_harness: dict[str, list[str]] = {}
    for row in rows:
        models = by_harness.setdefault(row["harness"], [])
        candidates = [row["model"], *(extra or {}).get((row["harness"], row["tier"]), [])]
        for model in candidates:
            if model not in models:
                models.append(model)
    return by_harness


def _discover_bound_models(rows: list[dict[str, str]]) -> dict[str, list[str] | Exception]:
    """Run discovery once per harness, asking about that harness's bound models."""
    return _discover(_models_by_harness(rows))


def _discover(by_harness: dict[str, list[str]]) -> dict[str, list[str] | Exception]:
    """Run discovery once per harness for the given candidate models."""
    from superharness.engine import model_router

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


def _accept_chains(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[str]]:
    """The adapter manifest's auth-compatible accept chain for each bound tier."""
    from superharness.engine import model_router

    chains: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        dispatch_tier = _BINDING_TO_DISPATCH_TIER.get(row["tier"])
        if dispatch_tier is None:
            continue
        auth_mode = model_router.detect_auth_mode_for_agent(row["harness"])
        chains[(row["harness"], row["tier"])] = model_router._tier_accept_chain(
            row["harness"], dispatch_tier, auth_mode
        )
    return chains


def propose_updates(
    classified: list[dict[str, str]],
    accept_chains: dict[tuple[str, str], list[str]],
    discovered: dict[str, list[str] | Exception],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Propose a replacement for each unavailable binding, and the providers to re-verify.

    A replacement is the first model of the adapter's accept chain that
    discovery confirmed; without one, the proposal is ``None`` and the binding
    needs a manual edit. A provider is re-verified only when every one of its
    bindings is confirmed available.
    """
    proposals: list[dict[str, Any]] = []
    for row in classified:
        if row.get("availability") != "unavailable":
            continue
        found = discovered.get(row["harness"])
        confirmed = set(found) if isinstance(found, list) else set()
        candidate = next(
            (m for m in accept_chains.get((row["harness"], row["tier"]), [])
             if m in confirmed and m != row["model"]),
            None,
        )
        reason = (
            "bound model unavailable; first confirmed model of the adapter accept chain"
            if candidate
            else "bound model unavailable and no accept-chain model confirmed; edit it by hand"
        )
        proposals.append({
            "harness": row["harness"],
            "tier": row["tier"],
            "current": row["model"],
            "proposed": candidate,
            "reason": reason,
        })

    by_provider: dict[str, list[str]] = {}
    for row in classified:
        by_provider.setdefault(row["provider"], []).append(row.get("availability", "unknown"))
    refresh = sorted(p for p, states in by_provider.items() if states and set(states) == {"available"})
    return proposals, refresh


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
    if stale:
        report["next_command"] = CATALOG_REFRESH_COMMAND
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
        click.echo(f"Refresh them from the catalog: {CATALOG_REFRESH_COMMAND}")
    for row in report["bindings"]:
        availability = f"  [{row['availability']}]" if "availability" in row else ""
        error = f"  {row['error']}" if row.get("error") else ""
        click.echo(
            f"  {row['harness']:<14} {row['tier']:<13} {row['model']}  ({row['provider']})"
            f"{availability}{error}"
        )


def write_bindings_atomically(path: Path, text: str) -> Path | None:
    """Replace ``path`` with ``text`` atomically; back up an existing file first.

    The backup is a byte-identical copy named ``<name>.bak-<UTC timestamp>``.
    The new content is written to a temporary file in the same directory and
    renamed over the target, so a failure never leaves a partial file. Returns
    the backup path, or None when there was nothing to back up.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.with_name(f"{path.name}.bak-{stamp}")
        shutil.copy2(path, backup)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return backup


def _manifest_bindings_text(today: date) -> str:
    """Build a starter bindings file from every adapter manifest's first choices."""
    from superharness.engine.adapter_registry import list_adapters, load_manifest

    harnesses: dict[str, Any] = {}
    for name in list_adapters():
        manifest = load_manifest(name)
        ladder: dict[str, Any] = {}
        for dispatch_tier, binding_tier in DISPATCH_TO_BINDING_TIER.items():
            chain = manifest.resolve_accept_chain(dispatch_tier, "unknown")
            model = chain[0] if chain else manifest.model_tiers.get(dispatch_tier, {}).get("id", "")
            if model:
                ladder[binding_tier] = {"id": model}
        if ladder:
            harnesses[name] = {
                "default_provider": MANIFEST_PROVIDER,
                "bindings": {MANIFEST_PROVIDER: ladder},
            }
    document = {
        "schema": SCHEMA_VERSION,
        "review_after_days": DEFAULT_REVIEW_AFTER_DAYS,
        "tiers": ["bulk", "default", "escalate-1", "escalate-2", "final-review"],
        "providers": {MANIFEST_PROVIDER: {"verified": today.isoformat()}},
        "harnesses": harnesses,
    }
    header = (
        "# superharness model bindings (schema 2).\n"
        "# Generated by `shux models init` from the adapter manifests.\n"
        "# Each harness uses its default_provider's ladder; edit ids freely,\n"
        "# then run `shux models check --probe` to confirm they are available.\n"
    )
    return header + yaml.safe_dump(document, sort_keys=False)


@click.group()
def main() -> None:
    """Check and maintain superharness's own model bindings file."""


def providers_confirmed_after_apply(
    classified: list[dict[str, str]], proposals: list[dict[str, Any]]
) -> list[str]:
    """Providers whose every binding is available once the confirmed replacements land."""
    replaced = {(p["harness"], p["tier"]) for p in proposals if p["proposed"]}
    states: dict[str, set[bool]] = {}
    for row in classified:
        ok = row.get("availability") == "available" or (row["harness"], row["tier"]) in replaced
        states.setdefault(row["provider"], set()).add(ok)
    return sorted(provider for provider, oks in states.items() if oks == {True})


def apply_updates(text: str, proposals: list[dict[str, Any]], providers: list[str], today: date) -> str:
    """Return ``text`` with the confirmed replacements and verified dates, comments kept."""
    import io

    from ruamel.yaml import YAML

    round_trip = YAML()
    round_trip.preserve_quotes = True
    document = round_trip.load(text)
    for proposal in proposals:
        if not proposal["proposed"]:
            continue
        harness = document["harnesses"][proposal["harness"]]
        provider = harness["default_provider"]
        harness["bindings"][provider][proposal["tier"]]["id"] = proposal["proposed"]
    if providers:
        if document.get("providers") is None:
            document["providers"] = {}
        for name in providers:
            if document["providers"].get(name) is None:
                document["providers"][name] = {}
            document["providers"][name]["verified"] = today
    out = io.StringIO()
    round_trip.dump(document, out)
    return out.getvalue()


def _update_report(bindings: BindingsFile) -> dict[str, Any]:
    """Probe the bindings and their accept-chain candidates; return proposals."""
    rows = _binding_rows(bindings)
    chains = _accept_chains(rows)
    discovered = _discover(_models_by_harness(rows, chains))
    classified = classify_bindings(rows, discovered)
    proposals, refresh = propose_updates(classified, chains, discovered)
    errors = {
        harness: f"{type(answer).__name__}: {answer}"
        for harness, answer in discovered.items()
        if isinstance(answer, Exception)
    }
    return {
        "path": str(bindings.path),
        "proposals": proposals,
        "verified_refresh": refresh,
        "verified_after_apply": providers_confirmed_after_apply(classified, proposals),
        "errors": errors,
    }


def _apply(bindings: BindingsFile, report: dict[str, Any]) -> None:
    """Write the confirmed proposals and verified dates; re-raise OSError after naming the file."""
    replacements = [p for p in report["proposals"] if p["proposed"]]
    providers = report["verified_after_apply"]
    if not replacements and not providers:
        click.echo("Nothing to apply: no confirmed replacement and no provider to re-verify.")
        return
    try:
        text = apply_updates(
            bindings.path.read_text(encoding="utf-8"), replacements, providers, date.today()
        )
        backup = write_bindings_atomically(bindings.path, text)
    except OSError as exc:
        click.echo(f"Could not write {bindings.path}: {exc}")
        raise
    if backup is not None:
        click.echo(f"Backup: {backup}")
    for p in replacements:
        click.echo(f"Applied: {p['harness']} {p['tier']} {p['current']} -> {p['proposed']}")
    if providers:
        click.echo(f"Verified today: {', '.join(providers)}")


def _without_provider(model_id: str, provider: str) -> str:
    """A binding id without its ``provider/`` prefix, as the catalog names it."""
    return model_id.removeprefix(f"{provider}/")


def _harness_check(found: list[str] | Exception | None, provider: str, model_id: str) -> str:
    """confirmed, unconfirmed or unknown: did the harness's discovery list this model?"""
    if isinstance(found, Exception) or not found:
        return "unknown"
    return "confirmed" if {model_id, f"{provider}/{model_id}"} & set(found) else "unconfirmed"


def _catalog_report(bindings: BindingsFile) -> tuple[dict[str, Any], int]:
    """Propose the newest same-family catalog model for each binding; write nothing.

    A proposal is applicable only when the provider's docs page confirms it (or
    the provider has none to check) and the harness's discovery lists it.
    Every catalog or docs failure is journaled.
    """
    from superharness.engine import model_catalog
    from superharness.engine.model_catalog_journal import record_catalog_failure

    report: dict[str, Any] = {"path": str(bindings.path), "proposals": [],
                              "not_in_catalog": [], "errors": {}}
    catalog = model_catalog.fetch_catalog()
    if isinstance(catalog, model_catalog.CatalogFailure):
        record_catalog_failure(catalog.source, catalog.reason)
        report["errors"][catalog.source] = catalog.reason
        return report, EXIT_ATTENTION

    candidates = []
    rows = _binding_rows(bindings)
    pending = set()
    for row in rows:
        bare = _without_provider(row["model"], row["provider"])
        if not any(m.id == bare for m in catalog.get(row["provider"], [])):
            report["not_in_catalog"].append(f"{row['harness']} {row['tier']} {row['model']}")
            pending.add(row["provider"])
            continue
        newer = model_catalog.newer_in_family(row["provider"], bare, catalog)
        if newer is not None:
            proposed = newer.id if bare == row["model"] else f"{row['provider']}/{newer.id}"
            candidates.append((row, newer, proposed))

    discovered = _discover(_models_by_harness(
        [{**row, "model": proposed} for row, _, proposed in candidates]
    ))
    docs = model_catalog.DocsChecker()
    for row, newer, proposed in candidates:
        check = docs.check(row["provider"], newer.id)
        if check.status == "unreachable" and f"{row['provider']} docs" not in report["errors"]:
            record_catalog_failure(f"{row['provider']} docs", check.reason)
            report["errors"][f"{row['provider']} docs"] = check.reason
        harness_check = _harness_check(discovered.get(row["harness"]), row["provider"], newer.id)
        report["proposals"].append({
            "harness": row["harness"], "tier": row["tier"], "provider": row["provider"],
            "current": row["model"], "proposed": proposed,
            "released": newer.release_date.isoformat(), "docs": check.status,
            "harness_check": harness_check,
            "apply": check.status in ("confirmed", "not-applicable") and harness_check == "confirmed",
        })
    for harness, answer in discovered.items():
        if isinstance(answer, Exception):
            report["errors"][harness] = f"{type(answer).__name__}: {answer}"
    pending.update(p["provider"] for p in report["proposals"] if not p["apply"])
    # A provider is re-verified only when every binding is the newest of its family once applied.
    report["verified_after_apply"] = sorted({row["provider"] for row in rows} - pending)
    return report, EXIT_OK


def _print_catalog_report(report: dict[str, Any]) -> None:
    click.echo(f"Model bindings: {report['path']} (catalog dry run, nothing written)")
    for source, reason in report["errors"].items():
        click.echo(f"  {source}: {reason}")
    if not report["proposals"] and not report["errors"]:
        click.echo("Every binding found in the catalog is the newest of its family.")
    for p in report["proposals"]:
        verdict = "applicable" if p["apply"] else "not applicable"
        click.echo(
            f"  {p['harness']:<14} {p['tier']:<13} {p['current']} -> {p['proposed']} "
            f"(released {p['released']}; docs {p['docs']}; harness {p['harness_check']}; {verdict})"
        )
    for entry in report["not_in_catalog"]:
        click.echo(f"  not in the catalog, left as is: {entry}")


def _describe(proposal: dict[str, Any]) -> str:
    return f"{proposal['harness']} {proposal['tier']} {proposal['current']} -> {proposal['proposed']}"


def _apply_catalog(bindings: BindingsFile, report: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Write the applicable catalog proposals; name the others.

    Returns the applied and skipped proposals as "harness tier current -> proposed".
    Raises OSError when the bindings file cannot be written.
    """
    for source, reason in report["errors"].items():
        click.echo(f"  {source}: {reason}")
    skipped = [p for p in report["proposals"] if not p["apply"]]
    for p in skipped:
        click.echo(f"Skipped: {_describe(p)} (docs {p['docs']}; harness {p['harness_check']})")
    applicable = [p for p in report["proposals"] if p["apply"]]
    _apply(bindings, {"proposals": applicable,
                      "verified_after_apply": report["verified_after_apply"]})
    return [_describe(p) for p in applicable], [_describe(p) for p in skipped]


def _refresh(bindings: BindingsFile, today: date) -> tuple[str, list[str], list[str], dict[str, str]]:
    """Run one unattended refresh; return (outcome, applied, skipped, errors)."""
    if bindings.status != "ok":
        return "failed", [], [], {
            "bindings": bindings.reason or f"{bindings.status} bindings file {bindings.path}"
        }
    if not stale_providers(bindings, today):
        return "skipped", [], [], {}
    report, code = _catalog_report(bindings)
    errors = dict(report["errors"])
    if code != EXIT_OK:
        return "failed", [], [], errors
    try:
        applied, skipped = _apply_catalog(bindings, report)
    except OSError as exc:
        errors["write"] = f"{bindings.path}: {exc}"
        return "failed", [], [], errors
    skipped += [f"{entry} (not in the catalog)" for entry in report["not_in_catalog"]]
    return ("partial" if skipped or errors else "ok"), applied, skipped, errors


@main.command("refresh")
def refresh_cmd() -> None:
    """Refresh stale bindings from the catalog, unattended; one receipt per run.

    Does nothing, without network, when no provider is past review_after_days.
    Otherwise applies the confirmed catalog proposals like `update --catalog --apply`.
    Exit 0 for skipped, ok and partial; exit 1 when the refresh failed or its
    receipt could not be written.
    """
    from superharness.engine.model_refresh import append_receipt, receipts_path

    outcome, applied, skipped, errors = _refresh(_bindings_file(), date.today())
    try:
        append_receipt(outcome, applied=applied, skipped=skipped, errors=errors)
    except OSError as exc:
        click.echo(f"Could not write the refresh receipt {receipts_path()}: {exc}", err=True)
        sys.exit(EXIT_ATTENTION)
    for source, reason in errors.items():
        click.echo(f"  {source}: {reason}")
    click.echo(f"Refresh {outcome}: {len(applied)} applied, {len(skipped)} skipped. "
               f"Receipt: {receipts_path()}")
    sys.exit(EXIT_ATTENTION if outcome == "failed" else EXIT_OK)


@main.command("update")
@click.option("--apply", "do_apply", is_flag=True, default=False,
              help="Write the confirmed replacements and verified dates (a backup is kept)")
@click.option("--catalog", "use_catalog", is_flag=True, default=False,
              help="Propose newer same-family models from the models.dev catalog (no key needed)")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON")
def update_cmd(do_apply: bool, use_catalog: bool, as_json: bool) -> None:
    """Propose replacements for unavailable bindings; write them with --apply."""
    bindings = _bindings_file()
    if bindings.status != "ok":
        report, code = _check_report(bindings, date.today())
        if as_json:
            click.echo(json.dumps(report, indent=2))
        else:
            _print_report(report)
        sys.exit(code)
    if use_catalog:
        catalog_report, code = _catalog_report(bindings)
        if do_apply and code == EXIT_OK:
            try:
                _apply_catalog(bindings, catalog_report)
            except OSError:
                sys.exit(EXIT_ATTENTION)
            sys.exit(EXIT_OK)
        if as_json:
            click.echo(json.dumps(catalog_report, indent=2))
        else:
            _print_catalog_report(catalog_report)
        sys.exit(code)
    report = _update_report(bindings)
    if do_apply:
        try:
            _apply(bindings, report)
        except OSError:
            sys.exit(EXIT_ATTENTION)
        sys.exit(EXIT_OK)
    if as_json:
        click.echo(json.dumps(report, indent=2))
        sys.exit(EXIT_OK)
    click.echo(f"Model bindings: {report['path']} (dry run, nothing written)")
    if not report["proposals"]:
        click.echo("No unavailable binding found.")
    for p in report["proposals"]:
        target = p["proposed"] or "no confirmed replacement; edit by hand"
        click.echo(f"  {p['harness']:<14} {p['tier']:<13} {p['current']} -> {target}")
    if report["verified_refresh"]:
        click.echo(f"Providers confirmed today: {', '.join(report['verified_refresh'])}")
    for harness, error in report["errors"].items():
        click.echo(f"  {harness}: discovery failed: {error}")
    sys.exit(EXIT_OK)


def _import_text(source: Path) -> str:
    """Return a schema-2 source file's text unchanged, or exit 1 naming the problem."""
    imported = load_bindings(source)
    if imported.status != "ok":
        click.echo(f"Cannot import {source}: {imported.reason}")
        sys.exit(EXIT_ATTENTION)
    try:
        return source.read_text(encoding="utf-8")
    except OSError as exc:
        click.echo(f"Cannot import {source}: {exc}")
        sys.exit(EXIT_ATTENTION)


@main.command("init")
@click.option("--force", is_flag=True, default=False,
              help="Replace an existing file (a timestamped backup is kept)")
@click.option("--from", "source", default=None, metavar="PATH",
              help="Import an existing schema-2 bindings file instead of the adapter manifests")
def init_cmd(force: bool, source: str | None) -> None:
    """Create the bindings file from the adapter manifests, or import one with --from."""
    from superharness.engine.model_router import _runtime_model_bindings_path

    path = _runtime_model_bindings_path()
    text = _import_text(Path(source)) if source else None
    if path.exists() and not force:
        click.echo(f"{path} already exists; pass --force to replace it (a backup is kept).")
        sys.exit(EXIT_ATTENTION)
    if text is None:
        text = _manifest_bindings_text(date.today())
    try:
        backup = write_bindings_atomically(path, text)
    except OSError as exc:
        click.echo(f"Could not write {path}: {exc}")
        sys.exit(EXIT_ATTENTION)
    if backup is not None:
        click.echo(f"Backup: {backup}")
    click.echo(f"Wrote {path}")


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


# --- shux models schedule -----------------------------------------------------

EXIT_UNSUPPORTED = 2

_HOME_OPTION = click.option(
    "--home", "home", default=None, type=click.Path(file_okay=False, path_type=Path),
    help="Home directory to install under (default: the current user's home)",
)


@main.group("schedule")
def schedule_group() -> None:
    """Run `shux models refresh` daily (launchd on macOS, a systemd user timer on Linux).

    install and uninstall are dry runs unless --apply. Windows is not supported.
    """


def _schedule_failed(action: str, exc: Exception) -> None:
    from superharness.engine.model_refresh_schedule import UnsupportedPlatform

    click.echo(f"{action} failed: {exc}")
    sys.exit(EXIT_UNSUPPORTED if isinstance(exc, UnsupportedPlatform) else EXIT_ATTENTION)


@schedule_group.command("status")
@_HOME_OPTION
def schedule_status_cmd(home: Path | None) -> None:
    """Show whether the scheduler is installed and loaded, and the last refresh receipt."""
    from superharness.engine import model_refresh_schedule as schedule
    from superharness.engine.model_refresh import last_receipt

    try:
        click.echo(schedule.status(schedule.backend_for(home or Path.home())))
    except schedule.ScheduleError as exc:
        _schedule_failed("Status", exc)
    receipt = last_receipt()
    click.echo(f"last refresh: {receipt['outcome']} at {receipt['at']}" if receipt
               else "last refresh: none recorded")


@schedule_group.command("install")
@_HOME_OPTION
@click.option("--hour", default=None, type=click.IntRange(0, 23), help="Hour of the daily run")
@click.option("--minute", default=None, type=click.IntRange(0, 59), help="Minute of the daily run")
@click.option("--apply", "do_apply", is_flag=True, default=False,
              help="Write and load the scheduler (without it, only print what would be done)")
def schedule_install_cmd(home: Path | None, hour: int | None, minute: int | None, do_apply: bool) -> None:
    """Install the daily refresh for the installed `shux`; a checkout `shux` is refused."""
    from superharness.engine import model_refresh_schedule as schedule

    try:
        backend = schedule.backend_for(home or Path.home())
        shux = schedule.resolve_installed_shux()
        files = backend.render(
            shux,
            schedule.DEFAULT_HOUR if hour is None else hour,
            schedule.DEFAULT_MINUTE if minute is None else minute,
        )
        if not do_apply:
            for path, text in files.items():
                click.echo(f"Would write {path} (dry run, nothing written):")
                click.echo(text)
            for cmd in backend.install_commands():
                click.echo(f"Would run: {' '.join(cmd)}")
            click.echo("Pass --apply to install.")
            return
        schedule.install(backend, files)
    except (schedule.ScheduleError, OSError) as exc:
        _schedule_failed("Install", exc)
    for path in files:
        click.echo(f"Wrote {path}")
    click.echo(f"Scheduler installed and loaded: `{shux} models refresh` runs daily.")


@schedule_group.command("uninstall")
@_HOME_OPTION
@click.option("--apply", "do_apply", is_flag=True, default=False,
              help="Unload and delete the scheduler (without it, only print what would be done)")
def schedule_uninstall_cmd(home: Path | None, do_apply: bool) -> None:
    """Unload the scheduler and delete everything install created."""
    from superharness.engine import model_refresh_schedule as schedule

    try:
        backend = schedule.backend_for(home or Path.home())
        if not do_apply:
            for cmd in backend.uninstall_commands():
                click.echo(f"Would run (if loaded): {' '.join(cmd)}")
            for path in (*backend.files(), *backend.extra_files()):
                click.echo(f"Would delete (if present): {path}")
            click.echo("Dry run, nothing changed. Pass --apply to uninstall.")
            return
        removed = schedule.uninstall(backend)
    except (schedule.ScheduleError, OSError) as exc:
        _schedule_failed("Uninstall", exc)
    for path in removed:
        click.echo(f"Deleted {path}")
    click.echo("Scheduler uninstalled.")



if __name__ == "__main__":
    main()
