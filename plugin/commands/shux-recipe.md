---
description: Switch the live RMDI delegation recipe — which delegation system routes tasks (DDAP-gated, atomic)
argument-hint: "<name> | list | events"
---

Run `shux recipe $ARGUMENTS` via Bash in the current project directory. Print stdout/stderr verbatim.

If it exits with code 3 asking for consent (a pinned seat crosses the openweight→frontier cost-class boundary), show the crossings to the user and ask whether to proceed; ONLY on an explicit yes re-run `shux recipe <name> --consent`. Never add --consent on your own.

If it reports the RMDI router unreachable, relay the error verbatim (it names the router URL and the `routing_strategy: native` escape hatch) — do not retry or work around it.
