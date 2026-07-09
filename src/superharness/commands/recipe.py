"""superharness recipe — switch the live RMDI delegation recipe (DDAP-gated).

The RMDI router (:8200) owns the delegation topology as named recipes; this
command is the Claude Code / terminal surface for switching which delegation
system is active, mid-session:

    shux recipe list                 list recipes (marks the active one)
    shux recipe <name> [--consent]   switch atomically (DDAP-solves every seat)
    shux recipe events [--limit N]   recent switch provenance events

Gate semantics mirror the pi TUI `/recipe` command:
  428 RECIPE_CONSENT_REQUIRED  a pinned seat crosses openweight→frontier —
                               interactive y/N confirm when stdin is a TTY,
                               otherwise exit 3 with the --consent retry hint.
  409 RECIPE_INFEASIBLE        printed verbatim, exit 3. Nothing was applied
                               (the switch is atomic).

The confirm IS the consent: there is no silent bypass of the cost-class gate.
"""

from __future__ import annotations

import getpass
import json
import sys

from superharness.engine import rmdi_client
from superharness.engine.rmdi_client import RmdiError, RmdiRouterDown

EXIT_GATE = 3


def _print_switch_result(res: dict, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(res, indent=2))
        return
    print(f"Activated recipe: {res.get('activeRecipe')}  (regime={res.get('regime', 'ddap')})")
    applied = res.get("applied", [])
    for a in applied:
        b = a.get("binding", {})
        spec = b.get("modelSpec", {})
        model = f"{spec.get('providerID')}/{spec.get('modelID')}"
        score = a.get("score")
        score_txt = f" score={score:.2f}" if isinstance(score, (int, float)) else ""
        kept = " (λ-retained)" if a.get("retainedIncumbent") else ""
        print(f"  {a.get('seat')} -> {model}  v{b.get('version')}{score_txt}{kept}")
    if not applied:
        print("  (no seats bound)")
    deferred = res.get("deferred", [])
    if deferred:
        print("Deferred (still lazy-bind on dispatch):")
        for d in deferred:
            print(f"  {d.get('seat')}: {d.get('code')}")


def _switch(name: str, consent: bool, json_mode: bool) -> int:
    user = getpass.getuser()
    try:
        res = rmdi_client.recipe_switch(name, user=user, consent=consent)
    except RmdiError as e:
        if e.status == 428 and e.code == "RECIPE_CONSENT_REQUIRED":
            crossings = e.payload.get("crossings", [])
            summary = ", ".join(
                f"{c.get('seat')}: {c.get('from') or '?'}->{c.get('to') or 'frontier'} ({c.get('model')})"
                for c in crossings
            )
            print(f"Recipe '{name}' rebinds {len(crossings)} seat(s) across a cost-class boundary:", file=sys.stderr)
            print(f"  {summary}", file=sys.stderr)
            if not sys.stdin.isatty():
                print(f"Non-interactive: re-run with `shux recipe {name} --consent` to accept.", file=sys.stderr)
                return EXIT_GATE
            sys.stderr.write("Proceed? [y/N]: ")
            sys.stderr.flush()
            ans = sys.stdin.readline().strip()
            if ans not in ("y", "Y", "yes", "YES"):
                print("Declined: recipe not activated (seats unchanged).", file=sys.stderr)
                return EXIT_GATE
            return _switch(name, consent=True, json_mode=json_mode)
        if e.status == 409 and e.code == "RECIPE_INFEASIBLE":
            print(f"Recipe '{name}' is INFEASIBLE — nothing applied (atomic).", file=sys.stderr)
            for f in e.payload.get("failures", []):
                print(f"  {f.get('seat')}: {f.get('code')} {json.dumps(f.get('detail'))}", file=sys.stderr)
            for c in e.payload.get("conflicts", []):
                print(f"  endpoint {c.get('endpoint')} pinned to: {', '.join(c.get('models', []))}", file=sys.stderr)
            return EXIT_GATE
        if e.status == 404:
            print(f"No recipe named '{name}'. Run `shux recipe list`.", file=sys.stderr)
            return 1
        print(str(e), file=sys.stderr)
        return 1

    _print_switch_result(res, json_mode)
    return 0


def _list(json_mode: bool) -> int:
    rows = rmdi_client.recipes()
    if json_mode:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No recipes loaded on the router.")
        return 0
    for r in rows:
        mark = "*" if r.get("active") else " "
        print(f" {mark} {r.get('name')}  seats={r.get('seats')} edges={r.get('edges')}"
              + (f"  advisor={r.get('advisor')}" if r.get("advisor") else ""))
        if r.get("description"):
            print(f"     {r['description']}")
    print("(* = active. `shux recipe <name>` to switch.)")
    return 0


def _events(limit: int, json_mode: bool) -> int:
    rows = rmdi_client.switch_events(limit)
    if json_mode:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("No switch events recorded.")
        return 0
    from datetime import datetime, timezone
    for ev in rows:
        at = datetime.fromtimestamp(ev.get("at", 0) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        who = ev.get("user") or ev.get("by")
        src = f" via {ev['source']}" if ev.get("source") else ""
        print(f"{at}  {ev.get('recipe')}  by {who}{src}  regime={ev.get('regime')}"
              + ("  (consent)" if ev.get("consent") else ""))
        for d in ev.get("decisions", []):
            if d.get("deferred"):
                print(f"    {d.get('seat')}: deferred {d['deferred'].get('code')}")
            else:
                score = d.get("score")
                score_txt = f" score={score:.2f}" if isinstance(score, (int, float)) else ""
                print(f"    {d.get('seat')}: {d.get('mode')} -> {d.get('modelKey')} v{d.get('bindingVersion')}{score_txt}")
    return 0


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in args
    consent = "--consent" in args
    args = [a for a in args if a not in ("--json", "--consent")]

    limit = 20
    if "--limit" in args:
        i = args.index("--limit")
        try:
            limit = int(args[i + 1])
            del args[i : i + 2]
        except (IndexError, ValueError):
            print("--limit needs an integer", file=sys.stderr)
            sys.exit(2)

    sub = args[0] if args else "list"
    try:
        if sub == "list":
            sys.exit(_list(json_mode))
        elif sub == "events":
            sys.exit(_events(limit, json_mode))
        else:
            sys.exit(_switch(sub, consent=consent, json_mode=json_mode))
    except RmdiRouterDown as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
